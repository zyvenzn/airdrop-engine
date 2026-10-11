from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db.models import AdminAuditLog, AdminUser, FarmingSession, PointBalance, Referral, Task, TaskSubmission, User
from app.db.session import SessionLocal
from app.security.dependencies import current_session, require_admin_roles
from app.security.rate_limit import enforce_rate_limit
from app.security.sessions import issue_session
from app.security.telegram import validate_telegram_init_data
from app.services.farming import claim_farming, start_farming
from app.services.referrals import attribute_referral
from app.services.tasks import submit_task


app = FastAPI(title=settings.app_name, version="0.3.0")


class TelegramAuthRequest(BaseModel):
    init_data: str = Field(min_length=1, max_length=16_384)


class FarmingStartRequest(BaseModel):
    # Reward rate is deliberately server-controlled; clients cannot raise their own rewards.
    duration_hours: int = Field(default=8, ge=1, le=24)


class TaskSubmitRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=36)
    evidence: str | None = Field(default=None, max_length=2000)


class ReferralAttributeRequest(BaseModel):
    referrer_id: str = Field(min_length=1, max_length=36)


class TaskReviewRequest(BaseModel):
    approved: bool


class TaskCreateRequest(BaseModel):
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
    session: dict = Depends(current_session),
) -> dict:
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
    session: dict = Depends(current_session),
) -> dict:
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
    session: dict = Depends(current_session),
) -> dict:
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
    session: dict = Depends(current_session),
) -> dict:
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
            metadata_json='{"status":"' + payload.status + '"}',
        ))
        result = {"id": task.id, "title": task.title, "status": task.status, "reward_points": task.reward_points}
    return result


@app.post(f"{settings.api_prefix}/admin/task-submissions/{{submission_id}}/review", tags=["admin"])
def post_admin_task_review(
    submission_id: str,
    payload: TaskReviewRequest,
    admin: dict = Depends(require_admin_roles("owner", "operator", "reviewer")),
) -> dict:
    from app.services.tasks import review_task

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
