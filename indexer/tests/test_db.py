"""Tests for `db.DatabaseManager` using mocked connections (no real DB)."""

import pytest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import asyncio

sys.path.insert(0, str(Path(__file__).parent.parent))

from db import DatabaseManager
from models import TgSyncState, EmbeddingCache, Chunk


class FakeConnection:
    def __init__(self):
        self.executed = []
        self._fetchrow_value = None
        self._fetch_values = []

    async def execute(self, sql, *args):  # noqa: D401
        self.executed.append((sql.strip(), args))
        return "OK"

    async def fetchrow(self, sql, *args):
        return self._fetchrow_value

    async def fetch(self, sql, *args):
        return self._fetch_values


def connection_cm(fake_conn):
    async def _acquire():
        class _Ctx:
            async def __aenter__(self_inner):
                return fake_conn

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        return _Ctx()

    return _acquire()


class DummyCtx:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_create_tables_executes_ddl():
    dbm = DatabaseManager("postgresql://user:pass@host/db")
    fake_conn = FakeConnection()
    with patch.object(dbm, "get_connection", return_value=DummyCtx(fake_conn)):
        await dbm.create_tables()
    assert any("CREATE TABLE" in call[0] for call in fake_conn.executed)


@pytest.mark.asyncio
async def test_sync_state_roundtrip():
    dbm = DatabaseManager("postgresql://user:pass@host/db")
    fake_conn = FakeConnection()
    state = TgSyncState(chat_id="chat1", last_message_id=123, last_edit_ts=456)

    # First call (fetchrow) returns None, second returns dict
    sequence = [
        None,
        {
            "chat_id": state.chat_id,
            "last_message_id": state.last_message_id,
            "last_edit_ts": state.last_edit_ts,
        },
    ]

    class SeqCtx(DummyCtx):
        async def __aenter__(self_inner):
            fake_conn._fetchrow_value = sequence.pop(0)
            return fake_conn

    with patch.object(dbm, "get_connection", side_effect=lambda: SeqCtx(fake_conn)):
        # update then get
        await dbm.update_sync_state(state)
        loaded = await dbm.get_sync_state(state.chat_id)
    assert loaded == state


@pytest.mark.asyncio
async def test_embedding_cache_fetch_and_store():
    dbm = DatabaseManager("postgresql://user:pass@host/db")
    fake_conn = FakeConnection()
    embedding = EmbeddingCache(
        text_hash="abc",
        model="text-embedding-3-small",
        dim=3,
        vector=b"\x00\x01\x02",
        lang="en",
        chunking_version=1,
        preprocess_version=1,
    )

    # First fetch returns None, second returns dict representing embedding
    sequence = [None, embedding.model]

    class EmbedCtx(DummyCtx):
        async def __aenter__(self_inner):
            if sequence and sequence[0] is None:
                fake_conn._fetchrow_value = None
            else:
                fake_conn._fetchrow_value = {
                    "text_hash": embedding.text_hash,
                    "model": embedding.model,
                    "dim": embedding.dim,
                    "vector": embedding.vector,
                    "lang": embedding.lang,
                    "chunking_version": embedding.chunking_version,
                    "preprocess_version": embedding.preprocess_version,
                }
            if sequence:
                sequence.pop(0)
            return fake_conn

    with patch.object(dbm, "get_connection", side_effect=lambda: EmbedCtx(fake_conn)):
        await dbm.cache_embedding(embedding)
        result = await dbm.get_cached_embedding(embedding.text_hash)
    assert result is not None
    assert result.text_hash == embedding.text_hash


@pytest.mark.asyncio
async def test_chunk_upsert_and_query():
    dbm = DatabaseManager("postgresql://user:pass@host/db")
    fake_conn = FakeConnection()
    chunk = Chunk(
        chunk_id="c1",
        chat_id="chat1",
        message_id=1,
        chunk_idx=0,
        text_hash="abc",
        message_date=1000,
        edit_date=None,
        deleted_at=None,
        sender="Alice",
        sender_username="alice",
        chat_type="private",
        thread_id=None,
        has_link=False,
    )

    # fetch returns the chunk after insert
    fake_conn._fetch_values = [{k: getattr(chunk, k) for k in chunk.model_fields}]

    with patch.object(dbm, "get_connection", return_value=DummyCtx(fake_conn)):
        await dbm.upsert_chunk(chunk)
        rows = await dbm.get_existing_chunks(chunk.chat_id, chunk.message_id)
    assert len(rows) == 1
    assert rows[0].chunk_id == chunk.chunk_id


@pytest.mark.asyncio
async def test_mark_chunks_deleted_executes_update():
    dbm = DatabaseManager("postgresql://user:pass@host/db")
    fake_conn = FakeConnection()
    executed_sql = {}

    with patch.object(dbm, "get_connection", return_value=DummyCtx(fake_conn)):
        await dbm.mark_chunks_deleted("chat1", 1, 999)
    assert any("UPDATE chunks SET deleted_at" in sql for sql, _ in fake_conn.executed)
