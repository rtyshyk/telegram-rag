"""Database models for indexer."""

from typing import Optional
from pydantic import BaseModel


class TgSyncState(BaseModel):
    """Sync state per chat."""

    chat_id: str
    last_message_id: Optional[int] = None
    last_edit_ts: Optional[int] = None


class EmbeddingCache(BaseModel):
    """Cached embedding for text."""

    text_hash: str
    model: str
    dim: int
    vector: bytes  # float32 array as bytes
    lang: Optional[str] = None
    chunking_version: int
    preprocess_version: int


class Chunk(BaseModel):
    """Processed message chunk."""

    chunk_id: str
    chat_id: str
    message_id: int
    chunk_idx: int
    text_hash: str
    message_date: int  # epoch seconds
    edit_date: Optional[int] = None
    deleted_at: Optional[int] = None
    sender: Optional[str] = None
    sender_username: Optional[str] = None
    chat_type: Optional[str] = None
    thread_id: Optional[int] = None
    has_link: bool = False


class VespaDocument(BaseModel):
    """Vespa document structure."""

    id: str
    chat_id: str
    message_id: int
    chunk_idx: int
    source_title: Optional[str] = None
    sender: Optional[str] = None
    sender_username: Optional[str] = None
    chat_type: Optional[str] = None
    message_date: int
    edit_date: Optional[int] = None
    deleted_at: Optional[int] = None
    thread_id: Optional[int] = None
    has_link: bool = False
    text: str
    bm25_text: str
    vector_small: Optional[dict] = None  # {"values": [float, ...]} for 1536-dim
    vector_large: Optional[dict] = None  # {"values": [float, ...]} for 3072-dim


class IndexerMetrics(BaseModel):
    """Runtime metrics."""

    messages_scanned: int = 0
    messages_indexed: int = 0
    chunks_written: int = 0
    embed_calls: int = 0
    embed_cached_hits: int = 0
    embed_cached_misses: int = 0
    vespa_feed_success: int = 0
    vespa_feed_retries: int = 0
    vespa_feed_failures: int = 0
    total_tokens: int = 0
    cost_estimate: float = 0.0
