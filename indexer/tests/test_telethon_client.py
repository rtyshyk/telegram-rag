"""Tests for TelethonClientWrapper (stub mode only)."""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from telethon_client import TelethonClientWrapper
from normalize import extract_chat_type
from settings import settings as real_settings


@pytest.mark.asyncio
async def test_resolve_chats_stub_mode():
    original = real_settings.telethon_stub
    real_settings.telethon_stub = True
    try:
        with patch("telethon_client.TelegramClient") as mock_client:
            wrapper = TelethonClientWrapper()
        result = await wrapper.resolve_chats(["group1", "<Saved Messages>"])
    finally:
        real_settings.telethon_stub = original
    assert "group1" in result and "<Saved Messages>" in result
    assert result["<Saved Messages>"]["type"] in {"saved", "group", "private"}


@pytest.mark.asyncio
async def test_stub_get_messages_limit():
    original = real_settings.telethon_stub
    real_settings.telethon_stub = True
    try:
        with patch("telethon_client.TelegramClient"):
            wrapper = TelethonClientWrapper()
        entity = "stub_entity"
        msgs = []
        async for m in wrapper.get_messages(entity, limit=5):
            msgs.append(m)
    finally:
        real_settings.telethon_stub = original
    assert len(msgs) == 5
    assert all("Test message" in m.text for m in msgs)


def _make_message(**kwargs):
    defaults = {
        "id": 1,
        "text": "Hello world",
        "sender": type(
            "User", (), {"first_name": "John", "last_name": "Doe", "username": "jdoe"}
        )(),
        "date": datetime.now(),
        "edit_date": None,
        "reply_to_msg_id": None,
        "forward": None,
        "action": None,
        "media": None,
    }
    defaults.update(kwargs)
    return type("Msg", (), defaults)()


def test_extract_message_data_basic():
    with patch("telethon_client.TelegramClient"):
        wrapper = TelethonClientWrapper()
    original = real_settings.telethon_stub
    real_settings.telethon_stub = True
    try:
        msg = _make_message()
        chat_entity = type(
            "Chat", (), {"megagroup": False, "channel": False, "user_id": 10}
        )()
        data = wrapper.extract_message_data(msg, chat_entity)
    finally:
        real_settings.telethon_stub = original
    assert data["message_id"] == 1
    assert data["sender"] == "John Doe"
    assert data["chat_type"] in {"private", "group", "channel", "unknown"}


def test_extract_message_data_forward():
    with patch("telethon_client.TelegramClient"):
        wrapper = TelethonClientWrapper()
    original = real_settings.telethon_stub
    real_settings.telethon_stub = True
    try:
        forward_sender = type(
            "User", (), {"first_name": "Alice", "last_name": "", "username": "alice"}
        )()
        forward = type("Fwd", (), {"from_name": None, "sender": forward_sender})()
        msg = _make_message(forward=forward)
        chat_entity = type(
            "Chat", (), {"megagroup": True, "channel": False, "user_id": None}
        )()
        data = wrapper.extract_message_data(msg, chat_entity)
    finally:
        real_settings.telethon_stub = original
    assert data["forward_from"] == "Alice"
    assert data["chat_type"] in {"group", "channel", "private", "unknown"}


@pytest.mark.asyncio
async def test_get_message_by_id_stub():
    original = real_settings.telethon_stub
    real_settings.telethon_stub = True
    try:
        with patch("telethon_client.TelegramClient"):
            wrapper = TelethonClientWrapper()
        msg = await wrapper.get_message_by_id("entity", 42)
    finally:
        real_settings.telethon_stub = original
    assert msg is not None
    assert msg.id == 42
    assert "Reply context" in msg.text
