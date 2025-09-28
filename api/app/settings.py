from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    All configuration knobs for the API.

    Kid-friendly tour of one search:

    1. You ask a question like "Where did we mention Katowice?" The query walks in
       the front door and Vespa grabs up to `search_seed_limit` (30 by default)
       promising "seed" messages.
     2. We keep the highest-ranking seeds overall, skipping ones that sit too
         close together in the timeline thanks to `search_seed_dedupe_message_gap`
         and `search_seed_dedupe_time_gap_seconds`.
     3. For every remaining seed we invite nearby messages to the party: up to
       `search_neighbor_message_window` IDs on either side (now 15 by default),
       or enough minutes to hit `search_neighbor_min_messages` using
       `search_neighbor_time_window_minutes` as the backup plan.
    4. Each growing conversation snippet is capped at
       `search_candidate_max_messages` messages and a soft
       `search_candidate_token_limit` tokens so nothing gets too long-winded.
     5. If `rerank_enabled` is true, we hand the best `rerank_candidate_limit`
         snippets to the VoyageAI model named in `rerank_model`, which re-sorts
         them by how helpful they seem.
     6. Tap the “Broaden search” button and we boost the limits:
         more Vespa seeds and extra rerank candidates (up to
         `search_expansion_max_level` times) so you can keep widening the net if
         you still need more context.
     7. Finally we return the top `search_context_max_return` snippets to the UI,
       ready for the chat answer or search page to show.
    """

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
    search_default_limit: int = (
        10  # Default number of search results returned to the UI
    )
    rerank_enabled: bool = False
    voyage_api_key: str | None = None
    voyage_stub: bool = False  # Use local scoring stub instead of hitting VoyageAI
    rerank_model: str = "rerank-2.5-lite"  # VoyageAI reranker model identifier
    rerank_candidate_limit: int = 40  # Max candidates passed to the reranker per query
    search_seed_limit: int = 30  # Max Vespa hits fetched before context expansion
    search_seed_dedupe_message_gap: int = (
        10  # Drop seeds within N message IDs of each other
    )
    search_seed_dedupe_time_gap_seconds: int = (
        120  # Drop seeds within N seconds of each other
    )
    search_neighbor_message_window: int = (
        15  # How many message IDs to expand around each seed
    )
    search_neighbor_time_window_minutes: int = (
        45  # Time window for neighbor fetch fallback
    )
    search_neighbor_min_messages: int = (
        5  # Minimum neighbor count before broadening window
    )
    search_candidate_max_messages: int = (
        80  # Cap on assembled messages per candidate snippet
    )
    search_candidate_token_limit: int = (
        1800  # Soft cap on tokens per candidate (≈x4 chars)
    )
    search_context_max_return: int = 25  # Max context snippets returned to the caller
    search_expansion_max_level: int = 3  # How many times the UI can widen search scope
    search_expansion_seed_step: int = 30  # Extra Vespa seeds fetched per widen level
    search_expansion_result_step: int = 5  # Extra snippets surfaced per widen level
    search_expansion_rerank_step: int = (
        40  # Extra rerank candidates pulled per widen level
    )
    log_level: str | None = None  # Override root log level (defaults to INFO)
    # Chat
    chat_default_k: int = 50
    chat_max_context_tokens: int = 50000
    chat_rate_limit_rpm: int = 30
    # Chat decision models (separate from user-selected model)
    chat_search_decision_model: str = "gpt-4.1"
    chat_reformulation_model: str = "gpt-4.1"


settings = Settings()
