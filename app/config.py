from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Airdrop Engine"
    app_env: str = "development"
    api_prefix: str = "/api/v1"
    telegram_bot_token: str = ""
    session_secret: str = ""
    telegram_initdata_max_age_seconds: int = 300
    database_url: str = "postgresql+psycopg://airdrop:airdrop@localhost:5432/airdrop_engine"
    redis_url: str = "redis://localhost:6379/0"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
