"""Tests for chats endpoint."""

import os
import sys
import pathlib
import bcrypt
import pytest
from unittest.mock import AsyncMock, Mock, patch
from fastapi.testclient import TestClient

# Set up environment like other tests
BASE = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(BASE))

os.environ.setdefault("APP_USER", "admin")
hash_pw = bcrypt.hashpw(b"password", bcrypt.gensalt()).decode()
os.environ.setdefault("APP_USER_HASH_BCRYPT", hash_pw)
os.environ.setdefault("SESSION_SECRET", "testsecret" * 2)

from app.main import app
from app.search import ChatInfo
import app.auth as auth


def reset_attempts():
    auth.login_attempts.clear()


def get_client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def login(client: TestClient):
    return client.post(
        "/auth/login", json={"username": "admin", "password": "password"}
    )


class TestChatsEndpoint:
    """Test chats endpoint."""

    def test_chats_requires_auth(self):
        """Test that chats endpoint requires authentication."""
        reset_attempts()
        client = get_client()
        response = client.get("/chats")
        assert response.status_code == 401

    @patch("app.search.VespaSearchClient.get_available_chats")
    def test_chats_returns_chat_list(self, mock_get_chats):
        """Test that chats endpoint returns chat list."""
        reset_attempts()
        client = get_client()

        # Mock the chat data
        mock_chats = [
            ChatInfo(
                chat_id="-1001234567890",
                source_title="Test Supergroup",
                chat_type="supergroup",
                message_count=150,
            ),
            ChatInfo(
                chat_id="123456789",
                source_title="Saved Messages",
                chat_type="private",
                message_count=50,
            ),
        ]
        mock_get_chats.return_value = mock_chats

        # Login first to get authenticated session
        login_response = login(client)
        assert login_response.status_code == 200

        response = client.get("/chats")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert len(data["chats"]) == 2
        assert data["chats"][0]["chat_id"] == "-1001234567890"
        assert data["chats"][0]["source_title"] == "Test Supergroup"
        assert data["chats"][1]["source_title"] == "Saved Messages"

    @patch("app.search.VespaSearchClient.get_available_chats")
    def test_chats_handles_errors(self, mock_get_chats):
        """Test that chats endpoint handles errors gracefully."""
        reset_attempts()
        client = get_client()

        mock_get_chats.side_effect = Exception("Vespa error")

        # Login first to get authenticated session
        login_response = login(client)
        assert login_response.status_code == 200

        response = client.get("/chats")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert data["chats"] == []
        assert "error" in data
