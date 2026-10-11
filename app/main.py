from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import settings
from app.db.models import PointBalance, User
from app.db.session import SessionLocal
from app.security.dependencies import current_session, require_admin_roles
from app.security.rate_limit import enforce_rate_limit
from app.security.sessions import issue_session
from app.security.telegram import validate_telegram_init_data

app = FastAPI(title=settings.app_name, version="0.2.0")


class TelegramAuthRequest(BaseModel):
    init_data: str = Field(min_length=1, max_length=16_384)


@app.get("/health/live", tags=["health"])
def live_health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(f"{settings.api_prefix}/auth/telegram", tags=["auth"])
def telegram_auth(payload: TelegramAuthRequest, request: Request) -> dict:
    enforce_rate_limit(request, action="telegram-auth", limit=10, window_seconds=60)
    verified = validate_telegram_init_data(
        payload.init_data,
        settings.telegram_bot_token,
        settings.telegram_initdata_max_age_seconds,
    )
    telegram_user = verified["user"]
    username = telegram_user.get("username")
    if username is not None:
        username = str(username)[:64]

    # User creation and initial balance are committed together.
    with SessionLocal.begin() as db:
        user = db.scalar(
            select(User).where(User.telegram_id == verified["telegram_id"]).with_for_update()
        )
        if user is None:
            user = User(
                telegram_id=verified["telegram_id"],
                username=username,
                status="active",
            )
            db.add(user)
            db.flush()
            db.add(PointBalance(user_id=user.id, available=0, pending=0))
            db.flush()
        else:
            if user.status != "active":
                from fastapi import HTTPException

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
    """Return the current active user's profile and points balance."""
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.id == session.get("sub")))
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


@app.get(f"{settings.api_prefix}/admin/me", tags=["admin"])
def get_admin_me(
    admin: dict = Depends(require_admin_roles("owner", "operator", "reviewer", "analyst")),
) -> dict:
    """Return the authenticated admin identity after role-based authorization."""
    return admin
