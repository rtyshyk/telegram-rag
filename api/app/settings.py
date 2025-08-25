from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Allow extra fields in environment variables
    )

    app_user: str
    app_user_hash_bcrypt: str
    session_secret: str
    session_ttl_hours: int = 24
    login_rate_max_attempts: int = 5
    login_rate_window_seconds: int = 900
    ui_origin: str | None = None

    # Search / Vespa configuration with sane defaults
    recency_halflife_days: int = 90
    vespa_query_timeout_ms: int = 250
    query_embed_cache_size: int = 256
    query_embed_cache_ttl_sec: int = 300
    search_default_limit: int = 20
    search_max_limit: int = 100

    # Map of UI model labels to embedding model ids
    model_map: dict[str, str] = {
        "gpt 5": "gpt-5",
        "gpt5 mini": "gpt-5-mini",
        "gpt5 nano": "gpt-5-nano",
    }

    # Deterministic embedding stub for tests
    openai_stub: bool = True


settings = Settings()
