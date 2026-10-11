from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.security.telegram import validate_telegram_init_data

app = FastAPI(title=settings.app_name, version="0.1.0")


class TelegramAuthRequest(BaseModel):
    init_data: str = Field(min_length=1, max_length=16_384)


@app.get("/health/live", tags=["health"])
def live_health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(f"{settings.api_prefix}/auth/telegram", tags=["auth"])
def telegram_auth(payload: TelegramAuthRequest) -> dict:
    verified = validate_telegram_init_data(
        payload.init_data,
        settings.telegram_bot_token,
        settings.telegram_initdata_max_age_seconds,
    )
    # Session issuance is intentionally not implemented until persistent user storage
    # and session signing/rotation policy are in place.
    return {
        "status": "authenticated",
        "telegram_id": verified["telegram_id"],
        "session_issuance": "pending",
    }
