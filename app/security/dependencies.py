from collections.abc import Callable

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select

from app.db.models import AdminUser
from app.db.session import SessionLocal
from app.security.sessions import verify_session


def current_session(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer session required")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Bearer session required")
    return verify_session(token)


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
