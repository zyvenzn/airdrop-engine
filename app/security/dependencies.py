from collections.abc import Callable

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select

from app.db.models import AdminUser, User
from app.db.session import SessionLocal
from app.security.sessions import verify_session


def current_session(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer session required")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Bearer session required")
    claims = verify_session(token)
    # Resolve signed identity against current DB state so suspension takes effect
    # immediately instead of waiting for the bearer token to expire.
    user_id = claims.get("sub")
    telegram_id = claims.get("tg")
    if not isinstance(user_id, str) or not isinstance(telegram_id, int):
        raise HTTPException(status_code=401, detail="Invalid session identity")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.id == user_id))
        if user is None or user.telegram_id != telegram_id or user.status != "active":
            raise HTTPException(status_code=401, detail="Session account is unavailable")
    return claims


def require_admin_roles(*allowed_roles: str) -> Callable:
    """Require an active admin account with one of the supplied roles."""
    valid_roles = {"owner", "operator", "reviewer", "analyst"}
    if not allowed_roles or not set(allowed_roles).issubset(valid_roles):
        raise ValueError("invalid admin role configuration")

    def dependency(session: dict = Depends(current_session)) -> dict:
        telegram_id = session.get("tg")
        if not isinstance(telegram_id, int):
            raise HTTPException(status_code=401, detail="Invalid session identity")
        with SessionLocal() as db:
            admin = db.scalar(select(AdminUser).where(AdminUser.telegram_id == telegram_id))
            if admin is None or admin.status != "active":
                raise HTTPException(status_code=403, detail="Admin access required")
            if admin.role not in allowed_roles:
                raise HTTPException(status_code=403, detail="Insufficient admin role")
            return {"admin_id": admin.id, "telegram_id": telegram_id, "role": admin.role}

    return dependency
