"""Settings and configuration."""

import os
from typing import List, Optional
from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""

    model_config = ConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    # OpenAI
    openai_api_key: str
    embed_model: str = "text-embedding-3-large"
    embed_dimensions: int = 3072
    embed_batch_size: int = 64
    embed_concurrency: int = 4

    # Telegram
    tg_api_id: int
    tg_api_hash: str
    tg_phone: str
    telethon_session_path: str = "/sessions/telethon.session"

    # Storage
    database_url: str

    # Vespa
    vespa_endpoint: str = "http://vespa:8080"

    # Chunking
    chunking_version: int = 1
    preprocess_version: int = 1
    reply_context_tokens: int = 120
    target_chunk_tokens: int = 1000
    chunk_overlap_tokens: int = 150

    # Budget / backoff
    daily_embed_budget_usd: float = 0.0  # 0 = disabled
    backoff_base_ms: int = 500
    backoff_max_ms: int = 30000

    # Stubs for testing
    openai_stub: bool = False
    telethon_stub: bool = False
    cohere_stub: bool = False

    # (Legacy Config class removed; using model_config for Pydantic v2.)


# Global settings instance
settings = Settings()


class CLIArgs(BaseModel):
    """CLI arguments."""

    once: bool = False
    chats: Optional[str] = None  # comma-separated chat names/IDs
    days: int = 30
    dry_run: bool = False
    limit_messages: Optional[int] = None
    embed_batch_size: Optional[int] = None
    embed_concurrency: Optional[int] = None
    sleep_ms: int = 0
    log_level: str = "INFO"

    def get_chat_list(self) -> List[str]:
        """Parse chat list from comma-separated string."""
        if not self.chats:
            return []
        return [chat.strip() for chat in self.chats.split(",") if chat.strip()]
