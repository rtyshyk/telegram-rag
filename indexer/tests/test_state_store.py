"""Tests for backfill state persistence."""

import json
from pathlib import Path

import pytest

from state import BackfillStateStore


@pytest.mark.asyncio
async def test_backfill_state_store_roundtrip(tmp_path):
    state_path = tmp_path / "backfill_state.json"
    store = BackfillStateStore(str(state_path))

    assert await store.get_last_message_id("chat-1") is None

    await store.update_chat("chat-1", 42)
    assert await store.get_last_message_id("chat-1") == 42

    # Reload from disk to verify persistence
    store_reloaded = BackfillStateStore(str(state_path))
    assert await store_reloaded.get_last_message_id("chat-1") == 42


@pytest.mark.asyncio
async def test_backfill_state_store_ignores_regressions(tmp_path):
    state_path = tmp_path / "backfill_state.json"
    store = BackfillStateStore(str(state_path))

    await store.update_chat("chat-1", 100)
    await store.update_chat("chat-1", 90)

    assert await store.get_last_message_id("chat-1") == 100

    # Verify file contents were not regressed
    payload = json.loads(Path(state_path).read_text())
    assert payload["chats"]["chat-1"]["last_message_id"] == 100
