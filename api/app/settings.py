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
    cors_allow_all: bool = False
    # Search / Embeddings
    openai_api_key: str | None = None
    embed_model: str = "text-embedding-3-large"
    embed_dimensions: int = 3072
    vespa_endpoint: str = "http://vespa:8080"
    search_default_limit: int = 20
    rerank_enabled: bool = False
    cohere_api_key: str | None = None
    rerank_model: str = "rerank-multilingual-v3.0"
    rerank_candidate_limit: int = 40
    cohere_stub: bool = False
    # Chat
    chat_default_k: int = 50
    chat_max_context_tokens: int = 50000
    chat_rate_limit_rpm: int = 30
    # Chat decision models (separate from user-selected model)
    chat_search_decision_model: str = "gpt-5-mini"
    chat_reformulation_model: str = "gpt-5-mini"


settings = Settings()
