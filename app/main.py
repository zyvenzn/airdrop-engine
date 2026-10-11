import json
import os
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db.models import AdminAuditLog, FarmingSession, PointBalance, PointsLedger, Task, TaskSubmission, User
from app.db.session import SessionLocal
from app.security.dependencies import current_session, require_admin_roles
from app.security.rate_limit import enforce_rate_limit
from app.security.sessions import issue_session
from app.security.telegram import validate_telegram_init_data
from app.services.farming import claim_farming, start_farming
from app.services.points import apply_points
from app.services.referrals import attribute_referral, qualify_referral
from app.services.tasks import review_task, submit_task


app = FastAPI(title=settings.app_name, version="0.4.0")

MINI_APP_FILE = Path(__file__).parent / "static" / "index.html"


@app.get("/", include_in_schema=False)
@app.get("/app", include_in_schema=False)
def mini_app() -> HTMLResponse:
    if not MINI_APP_FILE.is_file():
        raise HTTPException(status_code=503, detail="Mini App assets are not installed")
    html = MINI_APP_FILE.read_text(encoding="utf-8")
    bot_username = os.getenv("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")
    html = html.replace("window.APP_BOT_USERNAME||''", json.dumps(bot_username))
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


class TelegramAuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    init_data: str = Field(min_length=1, max_length=16_384)


class FarmingStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Reward rate is deliberately server-controlled; clients cannot raise their own rewards.
    duration_hours: int = Field(default=8, ge=1, le=24)


class TaskSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1, max_length=36)
    evidence: str | None = Field(default=None, max_length=2000)


class ReferralAttributeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    referrer_id: str = Field(min_length=1, max_length=36)


class TaskReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool


class TaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    task_type: str = Field(min_length=1, max_length=32)
    verification_type: str = Field(min_length=1, max_length=32)
    reward_points: int = Field(ge=1, le=1_000_000)
    status: Literal["draft", "active"] = "draft"


def _user_id(session: dict) -> str:
    user_id = session.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="Invalid session identity")
    return user_id


@app.get("/health/live", tags=["health"])
def live_health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(f"{settings.api_prefix}/auth/telegram", tags=["auth"])
def telegram_auth(payload: TelegramAuthRequest, request: Request) -> dict:
    enforce_rate_limit(request, action="telegram-auth", limit=10, window_seconds=60)
    if len(settings.session_secret) < 32:
        raise HTTPException(status_code=503, detail="Session signing is not configured")
    verified = validate_telegram_init_data(
        payload.init_data,
        settings.telegram_bot_token,
        settings.telegram_initdata_max_age_seconds,
    )
    telegram_user = verified["user"]
    username = telegram_user.get("username")
    if username is not None:
        username = str(username)[:64]

    with SessionLocal.begin() as db:
        user = db.scalar(
            select(User).where(User.telegram_id == verified["telegram_id"]).with_for_update()
        )
        if user is None:
            try:
                with db.begin_nested():
                    candidate = User(
                        telegram_id=verified["telegram_id"],
                        username=username,
                        status="active",
                    )
                    db.add(candidate)
                    db.flush()
                    db.add(PointBalance(user_id=candidate.id, available=0, pending=0))
                    db.flush()
                user = candidate
            except IntegrityError:
                user = db.scalar(
                    select(User).where(User.telegram_id == verified["telegram_id"]).with_for_update()
                )
                if user is None:
                    raise
        if user.status != "active":
            raise HTTPException(status_code=403, detail="Account is not active")
        user.username = username
        db.add(user)
        db.flush()
        user_id = user.id
        status_value = user.status

    token = issue_session(user_id=user_id, telegram_id=verified["telegram_id"])
    return {
        "status": "authenticated",
        "user_id": user_id,
        "telegram_id": verified["telegram_id"],
        "account_status": status_value,
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 3600,
    }


@app.get(f"{settings.api_prefix}/me", tags=["account"])
def get_me(session: dict = Depends(current_session)) -> dict:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.id == _user_id(session)))
        if user is None or user.status != "active":
            raise HTTPException(status_code=403, detail="Account is not active")
        balance = db.get(PointBalance, user.id)
        return {
            "user_id": user.id,
            "telegram_id": user.telegram_id,
            "username": user.username,
            "account_status": user.status,
            "points": {
                "available": balance.available if balance else 0,
                "pending": balance.pending if balance else 0,
            },
        }


@app.get(f"{settings.api_prefix}/farming", tags=["farming"])
def get_farming(session: dict = Depends(current_session)) -> dict:
    user_id = _user_id(session)
    with SessionLocal() as db:
        active = db.scalar(
            select(FarmingSession).where(
                FarmingSession.user_id == user_id, FarmingSession.status == "active"
            )
        )
        if active is None:
            return {"active": False, "session": None}
        return {
            "active": True,
            "session": {
                "id": active.id,
                "started_at": active.started_at,
                "ends_at": active.ends_at,
                "reward_points": active.reward_points,
                "status": active.status,
            },
        }


@app.post(f"{settings.api_prefix}/farming/start", tags=["farming"])
def post_farming_start(
    payload: FarmingStartRequest,
    request: Request,
    session: dict = Depends(current_session),
) -> dict:
    enforce_rate_limit(request, action="farming-start", limit=5, window_seconds=60)
    user_id = _user_id(session)
    try:
        with SessionLocal.begin() as db:
            farming = start_farming(
                db,
                user_id=user_id,
                duration_hours=payload.duration_hours,
            )
            result = {
                "id": farming.id,
                "started_at": farming.started_at,
                "ends_at": farming.ends_at,
                "reward_points": farming.reward_points,
                "status": farming.status,
            }
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="An active farming session already exists") from exc
    return result


@app.post(f"{settings.api_prefix}/farming/{{session_id}}/claim", tags=["farming"])
def post_farming_claim(
    session_id: str,
    request: Request,
    session: dict = Depends(current_session),
) -> dict:
    enforce_rate_limit(request, action="farming-claim", limit=10, window_seconds=60)
    user_id = _user_id(session)
    try:
        with SessionLocal.begin() as db:
            farming = claim_farming(db, user_id=user_id, session_id=session_id)
            result = {
                "id": farming.id,
                "status": farming.status,
                "claimed_at": farming.claimed_at,
                "reward_points": farming.reward_points,
            }
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result


@app.get(f"{settings.api_prefix}/tasks", tags=["tasks"])
def get_tasks(session: dict = Depends(current_session)) -> dict:
    _user_id(session)
    with SessionLocal() as db:
        tasks = db.scalars(select(Task).where(Task.status == "active").order_by(Task.created_at.desc())).all()
        return {"items": [
            {"id": task.id, "title": task.title, "description": task.description,
             "task_type": task.task_type, "verification_type": task.verification_type,
             "reward_points": task.reward_points}
            for task in tasks
        ]}


@app.post(f"{settings.api_prefix}/tasks/submit", tags=["tasks"])
def post_task_submit(
    payload: TaskSubmitRequest,
    request: Request,
    session: dict = Depends(current_session),
) -> dict:
    enforce_rate_limit(request, action="task-submit", limit=10, window_seconds=60)
    user_id = _user_id(session)
    try:
        with SessionLocal.begin() as db:
            submission = submit_task(
                db, user_id=user_id, task_id=payload.task_id, evidence=payload.evidence
            )
            result = {"id": submission.id, "task_id": submission.task_id, "status": submission.status}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Task has already been submitted") from exc
    return result


@app.post(f"{settings.api_prefix}/referrals/attribute", tags=["referrals"])
def post_referral_attribute(
    payload: ReferralAttributeRequest,
    request: Request,
    session: dict = Depends(current_session),
) -> dict:
    enforce_rate_limit(request, action="referral-attribute", limit=5, window_seconds=60)
    referred_id = _user_id(session)
    try:
        with SessionLocal.begin() as db:
            referral = attribute_referral(
                db, referrer_id=payload.referrer_id, referred_id=referred_id
            )
            result = {"id": referral.id, "status": referral.status}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Referral has already been attributed") from exc
    return result


@app.get(f"{settings.api_prefix}/tasks/submissions/me", tags=["tasks"])
def get_my_task_submissions(session: dict = Depends(current_session)) -> dict:
    user_id = _user_id(session)
    with SessionLocal() as db:
        submissions = db.scalars(
            select(TaskSubmission)
            .where(TaskSubmission.user_id == user_id)
            .order_by(TaskSubmission.submitted_at.desc())
        ).all()
        return {"items": [
            {"id": item.id, "task_id": item.task_id, "status": item.status,
             "submitted_at": item.submitted_at, "verified_at": item.verified_at}
            for item in submissions
        ]}


@app.get(f"{settings.api_prefix}/admin/task-submissions", tags=["admin"])
def get_admin_task_submissions(
    status: Literal["pending", "approved", "rejected"] = "pending",
    admin: dict = Depends(require_admin_roles("owner", "operator", "reviewer", "analyst")),
) -> dict:
    with SessionLocal() as db:
        submissions = db.scalars(
            select(TaskSubmission)
            .where(TaskSubmission.status == status)
            .order_by(TaskSubmission.submitted_at.asc())
            .limit(100)
        ).all()
        return {"items": [
            {"id": item.id, "user_id": item.user_id, "task_id": item.task_id,
             "status": item.status, "evidence": item.evidence, "submitted_at": item.submitted_at}
            for item in submissions
        ]}


@app.get(f"{settings.api_prefix}/admin/me", tags=["admin"])
def get_admin_me(
    admin: dict = Depends(require_admin_roles("owner", "operator", "reviewer", "analyst")),
) -> dict:
    return admin


@app.post(f"{settings.api_prefix}/admin/tasks", tags=["admin"])
def post_admin_task(
    payload: TaskCreateRequest,
    admin: dict = Depends(require_admin_roles("owner", "operator")),
) -> dict:
    with SessionLocal.begin() as db:
        task = Task(
            title=payload.title,
            description=payload.description,
            task_type=payload.task_type,
            verification_type=payload.verification_type,
            reward_points=payload.reward_points,
            status=payload.status,
        )
        db.add(task)
        db.flush()
        db.add(AdminAuditLog(
            admin_id=admin["admin_id"], action="task.create",
            target_type="task", target_id=task.id,
            metadata_json=json.dumps({"status": payload.status}, separators=(",", ":")),
        ))
        result = {"id": task.id, "title": task.title, "status": task.status, "reward_points": task.reward_points}
    return result


@app.post(f"{settings.api_prefix}/admin/task-submissions/{{submission_id}}/review", tags=["admin"])
def post_admin_task_review(
    submission_id: str,
    payload: TaskReviewRequest,
    request: Request,
    admin: dict = Depends(require_admin_roles("owner", "operator", "reviewer")),
) -> dict:
    enforce_rate_limit(request, action="admin-task-review", limit=60, window_seconds=60)
    try:
        with SessionLocal.begin() as db:
            submission = review_task(
                db, submission_id=submission_id, approved=payload.approved,
                reviewer_id=admin["admin_id"],
            )
            db.add(AdminAuditLog(
                admin_id=admin["admin_id"],
                action="task_submission.approve" if payload.approved else "task_submission.reject",
                target_type="task_submission", target_id=submission.id,
                metadata_json="{}",
            ))
            result = {"id": submission.id, "status": submission.status, "verified_at": submission.verified_at}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result


class ReferralQualifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reward_points: int = Field(ge=1, le=1_000_000)


@app.post(f"{settings.api_prefix}/admin/referrals/{{referral_id}}/qualify", tags=["admin"])
def post_admin_referral_qualify(
    referral_id: str,
    payload: ReferralQualifyRequest,
    request: Request,
    admin: dict = Depends(require_admin_roles("owner", "operator")),
) -> dict:
    enforce_rate_limit(request, action="admin-referral-qualify", limit=30, window_seconds=60)
    try:
        with SessionLocal.begin() as db:
            referral = qualify_referral(
                db, referral_id=referral_id, reward_points=payload.reward_points
            )
            db.add(AdminAuditLog(
                admin_id=admin["admin_id"],
                action="referral.qualify",
                target_type="referral",
                target_id=referral.id,
                metadata_json=json.dumps({"reward_points": payload.reward_points}, separators=(",", ":")),
            ))
            result = {
                "id": referral.id,
                "status": referral.status,
                "qualified_at": referral.qualified_at,
            }
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result


GAME_DAILY_LIMIT = 20
GAME_TAP_REWARD = 2


def _game_status(db, user_id: str, day_key: str) -> dict:
    taps = db.scalar(
        select(func.count(PointsLedger.id)).where(
            PointsLedger.user_id == user_id,
            PointsLedger.event_type == "game_tap",
            PointsLedger.reference_id == day_key,
        )
    ) or 0
    return {
        "day": day_key,
        "taps_used": taps,
        "taps_remaining": max(0, GAME_DAILY_LIMIT - taps),
        "daily_limit": GAME_DAILY_LIMIT,
        "points_per_tap": GAME_TAP_REWARD,
        "points_earned_today": taps * GAME_TAP_REWARD,
    }


@app.get(f"{settings.api_prefix}/game/status", tags=["game"])
def get_game_status(session: dict = Depends(current_session)) -> dict:
    user_id = _user_id(session)
    day_key = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).date().isoformat()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.id == user_id))
        if user is None or user.status != "active":
            raise HTTPException(status_code=403, detail="Account is not active")
        return _game_status(db, user_id, day_key)


@app.post(f"{settings.api_prefix}/game/tap", tags=["game"])
def post_game_tap(request: Request, session: dict = Depends(current_session)) -> dict:
    enforce_rate_limit(request, action="game-tap", limit=30, window_seconds=60)
    user_id = _user_id(session)
    day_key = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).date().isoformat()
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None or user.status != "active":
            raise HTTPException(status_code=403, detail="Account is not active")
        status = _game_status(db, user_id, day_key)
        if status["taps_remaining"] <= 0:
            raise HTTPException(status_code=429, detail="Daily core taps used. Come back tomorrow.")
        tap_number = status["taps_used"] + 1
        apply_points(
            db,
            user_id=user_id,
            amount=GAME_TAP_REWARD,
            event_type="game_tap",
            reference_id=day_key,
            idempotency_key=f"game-tap:{user_id}:{day_key}:{tap_number}",
        )
        result = _game_status(db, user_id, day_key)
        result["awarded_points"] = GAME_TAP_REWARD
        result["tap_number"] = tap_number
    return result
