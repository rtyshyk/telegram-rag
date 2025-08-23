from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_user: str
    app_user_hash_bcrypt: str
    session_secret: str
    session_ttl_hours: int = 24
    login_rate_max_attempts: int = 5
    login_rate_window_seconds: int = 900
    ui_origin: str | None = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
