"""Database operations.

Adds a lightweight fallback stub for ``asyncpg`` when running under a Python
version where binary wheels are not yet available (e.g. early Python 3.13).
This lets unit tests (which fully mock DB interactions) import the module
without requiring the native dependency build. The real package will be used
when installed; otherwise the stub provides only the minimal surface actually
accessed in tests / initialization.
"""

import asyncio
import logging
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager
from types import SimpleNamespace

try:  # pragma: no cover - exercised implicitly
    import asyncpg  # type: ignore
except Exception:  # ImportError or build-time failure

    class _StubConnection:  # pragma: no cover - trivial
        async def execute(self, *args: Any, **kwargs: Any):  # noqa: D401
            return "OK"

        async def fetchrow(self, *args: Any, **kwargs: Any):  # noqa: D401
            return None

        async def fetch(self, *args: Any, **kwargs: Any):  # noqa: D401
            return []

    class _StubPool:  # pragma: no cover - trivial
        async def acquire(self):  # noqa: D401
            return _StubConnection()

        async def release(self, _conn):  # noqa: D401
            return None

        async def close(self):  # noqa: D401
            return None

    async def create_pool(*_args: Any, **_kwargs: Any):  # pragma: no cover
        return _StubPool()

    asyncpg = SimpleNamespace(create_pool=create_pool, Pool=_StubPool)  # type: ignore

from models import TgSyncState, EmbeddingCache, Chunk

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages database connections and operations."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        # Using Any to allow fallback stub namespace when asyncpg isn't installed
        self.pool: Optional[Any] = None

    async def initialize(self):
        """Initialize database pool and create tables."""
        self.pool = await asyncpg.create_pool(
            self.database_url, min_size=2, max_size=10, command_timeout=60
        )
        await self.create_tables()

    async def close(self):
        """Close database pool."""
        if self.pool:
            await self.pool.close()

    @asynccontextmanager
    async def get_connection(self):
        """Get database connection from pool."""
        if not self.pool:
            raise RuntimeError("Database not initialized")

        conn = await self.pool.acquire()
        try:
            yield conn
        finally:
            await self.pool.release(conn)

    async def create_tables(self):
        """Create required tables."""
        sql = """
        -- Track per-chat sync state
        CREATE TABLE IF NOT EXISTS tg_sync_state (
          chat_id TEXT PRIMARY KEY,
          last_message_id BIGINT,
          last_edit_ts BIGINT,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        -- Embedding cache
        CREATE TABLE IF NOT EXISTS embedding_cache (
          text_hash TEXT PRIMARY KEY,
          model TEXT NOT NULL,
          dim INT NOT NULL,
          vector BYTEA NOT NULL,
          lang TEXT,
          chunking_version INT NOT NULL,
          preprocess_version INT NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        -- Ingested chunks
        CREATE TABLE IF NOT EXISTS chunks (
          chunk_id TEXT PRIMARY KEY,
          chat_id TEXT NOT NULL,
          message_id BIGINT NOT NULL,
          chunk_idx INT NOT NULL,
          text_hash TEXT NOT NULL,
          message_date BIGINT NOT NULL,
          edit_date BIGINT,
          deleted_at BIGINT,
          sender TEXT,
          sender_username TEXT,
          chat_username TEXT,
          chat_type TEXT,
          thread_id BIGINT,
          has_link BOOL DEFAULT FALSE
        );
        ALTER TABLE chunks ADD COLUMN IF NOT EXISTS chat_username TEXT;

        CREATE INDEX IF NOT EXISTS idx_chunks_chat_msg ON chunks(chat_id, message_id);
        CREATE INDEX IF NOT EXISTS idx_chunks_texthash ON chunks(text_hash);
        """

        async with self.get_connection() as conn:
            await conn.execute(sql)

        logger.info("Database tables created/verified")

    async def get_sync_state(self, chat_id: str) -> Optional[TgSyncState]:
        """Get sync state for a chat."""
        async with self.get_connection() as conn:
            row = await conn.fetchrow(
                "SELECT chat_id, last_message_id, last_edit_ts FROM tg_sync_state WHERE chat_id = $1",
                chat_id,
            )
            if row:
                return TgSyncState(**dict(row))
            return None

    async def update_sync_state(self, state: TgSyncState):
        """Update sync state for a chat."""
        async with self.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO tg_sync_state (chat_id, last_message_id, last_edit_ts, updated_at)
                VALUES ($1, $2, $3, now())
                ON CONFLICT (chat_id) DO UPDATE SET
                    last_message_id = EXCLUDED.last_message_id,
                    last_edit_ts = EXCLUDED.last_edit_ts,
                    updated_at = now()
                """,
                state.chat_id,
                state.last_message_id,
                state.last_edit_ts,
            )

    async def get_cached_embedding(self, text_hash: str) -> Optional[EmbeddingCache]:
        """Get cached embedding by text hash."""
        async with self.get_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT text_hash, model, dim, vector, lang, chunking_version, preprocess_version
                FROM embedding_cache WHERE text_hash = $1
                """,
                text_hash,
            )
            if row:
                return EmbeddingCache(**dict(row))
            return None

    async def cache_embedding(self, embedding: EmbeddingCache):
        """Cache an embedding."""
        async with self.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO embedding_cache (text_hash, model, dim, vector, lang, chunking_version, preprocess_version, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, now())
                ON CONFLICT (text_hash) DO NOTHING
                """,
                embedding.text_hash,
                embedding.model,
                embedding.dim,
                embedding.vector,
                embedding.lang,
                embedding.chunking_version,
                embedding.preprocess_version,
            )

    async def get_existing_chunks(self, chat_id: str, message_id: int) -> List[Chunk]:
        """Get existing chunks for a message."""
        async with self.get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT chunk_id, chat_id, message_id, chunk_idx, text_hash, message_date,
                       edit_date, deleted_at, sender, sender_username, chat_username, chat_type, thread_id, has_link
                FROM chunks WHERE chat_id = $1 AND message_id = $2
                """,
                chat_id,
                message_id,
            )
            return [Chunk(**dict(row)) for row in rows]

    async def upsert_chunk(self, chunk: Chunk):
        """Insert or update a chunk."""
        async with self.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO chunks (
                    chunk_id, chat_id, message_id, chunk_idx, text_hash, message_date,
                    edit_date, deleted_at, sender, sender_username, chat_username, chat_type, thread_id, has_link
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                ON CONFLICT (chunk_id) DO UPDATE SET
                    text_hash = EXCLUDED.text_hash,
                    edit_date = EXCLUDED.edit_date,
                    deleted_at = EXCLUDED.deleted_at,
                    sender = EXCLUDED.sender,
                    sender_username = EXCLUDED.sender_username,
                    chat_username = EXCLUDED.chat_username,
                    chat_type = EXCLUDED.chat_type,
                    thread_id = EXCLUDED.thread_id,
                    has_link = EXCLUDED.has_link
                """,
                chunk.chunk_id,
                chunk.chat_id,
                chunk.message_id,
                chunk.chunk_idx,
                chunk.text_hash,
                chunk.message_date,
                chunk.edit_date,
                chunk.deleted_at,
                chunk.sender,
                chunk.sender_username,
                chunk.chat_username,
                chunk.chat_type,
                chunk.thread_id,
                chunk.has_link,
            )

    async def mark_chunks_deleted(self, chat_id: str, message_id: int, deleted_at: int):
        """Mark all chunks for a message as deleted."""
        async with self.get_connection() as conn:
            await conn.execute(
                "UPDATE chunks SET deleted_at = $3 WHERE chat_id = $1 AND message_id = $2",
                chat_id,
                message_id,
                deleted_at,
            )
