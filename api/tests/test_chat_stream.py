"""Tests for chat streaming functionality (moved from app/ to tests/)."""

import pathlib
import sys
import json
from unittest.mock import Mock, AsyncMock, patch
import pytest

# Ensure we can import the application package (`app.*`)
BASE = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(BASE))

from app.chat import (  # noqa: E402
    ChatService,
    ChatRequest,
    ChatStreamChunk,
    ChatMessage,
)


@pytest.fixture
def mock_search_client():
    client = Mock()
    client.search = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_openai_client():
    return Mock()


@pytest.fixture
def chat_service(mock_openai_client):
    # Patch settings & search client creation inside ChatService initialization
    with patch("app.chat.get_search_client"), patch(
        "app.chat.settings"
    ) as mock_settings:
        mock_settings.chat_max_context_tokens = 50000
        mock_settings.openai_api_key = "test-key"
        mock_settings.chat_default_model_id = "gpt-5"

        service = ChatService()
        service.openai_client = mock_openai_client
        return service


@pytest.mark.asyncio
async def test_chat_stream_no_results(chat_service, mock_search_client):
    with patch("app.chat.get_search_client", return_value=mock_search_client):
        request = ChatRequest(q="test query", model_id="gpt-5")

        chunks = []
        async for chunk_data in chat_service.chat_stream(request, "test_user"):
            if chunk_data.startswith("data: "):
                chunk = json.loads(chunk_data[6:])
                chunks.append(ChatStreamChunk(**chunk))

        # Expect at least search, a no-data content, and end chunks
        assert len(chunks) >= 3
        types = {c.type for c in chunks}
        assert {"search", "content", "end"}.issubset(types)


@pytest.mark.asyncio
async def test_chat_stream_with_openai_response(chat_service):
    mock_search_results = [
        Mock(
            id="1",
            chat_id="-123",
            message_id=456,
            chunk_idx=0,
            source_title="Test Chat",
            message_date=1234567890,
            text="Test content for context",
        )
    ]

    mock_chunks = [
        Mock(choices=[Mock(delta=Mock(content="Hello"))], usage=None),
        Mock(choices=[Mock(delta=Mock(content=" world!"))], usage=None),
        Mock(
            choices=[Mock(delta=Mock(content=None))],
            usage=Mock(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        ),
    ]

    async def mock_stream():
        for ch in mock_chunks:
            yield ch

    chat_service.openai_client.chat.completions.create = AsyncMock()
    chat_service.openai_client.chat.completions.create.return_value = mock_stream()

    with patch("app.chat.get_search_client") as mock_get_client, patch.object(
        chat_service, "_build_search_request"
    ), patch("app.chat.ContextAssembler") as mock_assembler_class:
        mock_client = Mock()
        mock_client.search = AsyncMock(return_value=mock_search_results)
        mock_get_client.return_value = mock_client

        mock_assembler = Mock()
        mock_assembler.assemble_context.return_value = ("context", [0])
        mock_assembler.count_tokens.return_value = 100
        mock_assembler_class.return_value = mock_assembler

        request = ChatRequest(q="test query", model_id="gpt-5")
        chunks = []
        async for chunk_data in chat_service.chat_stream(request, "test_user"):
            if chunk_data.startswith("data: "):
                chunk = json.loads(chunk_data[6:])
                chunks.append(ChatStreamChunk(**chunk))

        types = {c.type for c in chunks}
        # Expect search, start, content (>=2), citations, end
        assert {"search", "start", "content", "citations", "end"}.issubset(types)
        content_chunks = [c for c in chunks if c.type == "content"]
        assert len(content_chunks) >= 2


@pytest.mark.asyncio
async def test_chat_skips_reformulation_for_short_lexical_query(
    chat_service,
):
    """Single-keyword + history: search uses the raw query (no LLM reformulation)."""

    mock_chunks = [
        Mock(choices=[Mock(delta=Mock(content="ok"))], usage=None),
        Mock(
            choices=[Mock(delta=Mock(content=None))],
            usage=Mock(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        ),
    ]

    async def mock_stream():
        for ch in mock_chunks:
            yield ch

    chat_service.openai_client.chat.completions.create = AsyncMock()
    chat_service.openai_client.chat.completions.create.return_value = mock_stream()

    chat_service.search_decision_maker.should_search = AsyncMock(return_value=True)
    chat_service.query_reformulator.reformulate_query = AsyncMock(
        side_effect=AssertionError("reformulate_query should not be called")
    )

    mock_search_results = [
        Mock(
            id="syn-1",
            chat_id="10001",
            message_id=1,
            chunk_idx=0,
            source_title="Synthetic",
            message_date=1234567890,
            text="Synthetic mention хоумстейджер for recommendations.",
        )
    ]

    with patch("app.chat.get_search_client") as mock_get_client, patch.object(
        chat_service, "_build_search_request"
    ), patch("app.chat.ContextAssembler") as mock_assembler_class:
        mock_client = Mock()
        mock_client.search = AsyncMock(return_value=mock_search_results)
        mock_get_client.return_value = mock_client

        mock_assembler = Mock()
        mock_assembler.assemble_context.return_value = (
            "context with хоумстейджер",
            [0],
        )
        mock_assembler.count_tokens.return_value = 50
        mock_assembler_class.return_value = mock_assembler

        request = ChatRequest(
            q="хоумстейджеры",
            model_id="gpt-5",
            history=[
                ChatMessage(role="user", content="prior"),
                ChatMessage(role="assistant", content="ok"),
            ],
        )
        chunks = []
        async for chunk_data in chat_service.chat_stream(request, "test_user"):
            if chunk_data.startswith("data: "):
                chunk = json.loads(chunk_data[6:])
                chunks.append(ChatStreamChunk(**chunk))

    types = [c.type for c in chunks]
    assert "reformulate" not in types
    chat_service.query_reformulator.reformulate_query.assert_not_called()


@pytest.mark.asyncio
async def test_chat_canonical_homestager_skips_reformulation_and_searches_raw_query(
    chat_service,
):
    """Incident query: посоветуйте хоумстейджера — no reformulation, same string to search."""

    canonical_q = "посоветуйте хоумстейджера"

    mock_chunks = [
        Mock(choices=[Mock(delta=Mock(content="ok"))], usage=None),
        Mock(
            choices=[Mock(delta=Mock(content=None))],
            usage=Mock(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        ),
    ]

    async def mock_stream():
        for ch in mock_chunks:
            yield ch

    chat_service.openai_client.chat.completions.create = AsyncMock()
    chat_service.openai_client.chat.completions.create.return_value = mock_stream()

    chat_service.search_decision_maker.should_search = AsyncMock(return_value=True)
    chat_service.query_reformulator.reformulate_query = AsyncMock(
        side_effect=AssertionError("reformulate_query should not be called")
    )

    mock_search_results = [
        Mock(
            id="syn-hs-1",
            chat_id="10001",
            message_id=7,
            chunk_idx=0,
            source_title="Synthetic",
            message_date=1_700_000_000,
            text="Synthetic: наш хоумстейджер, контакт @testuser.",
        )
    ]

    with patch("app.chat.get_search_client") as mock_get_client, patch(
        "app.chat.ContextAssembler"
    ) as mock_assembler_class:
        mock_client = Mock()
        mock_client.search = AsyncMock(return_value=mock_search_results)
        mock_get_client.return_value = mock_client

        mock_assembler = Mock()
        mock_assembler.assemble_context.return_value = ("ctx", [0])
        mock_assembler.count_tokens.return_value = 20
        mock_assembler_class.return_value = mock_assembler

        request = ChatRequest(
            q=canonical_q,
            model_id="gpt-5",
            history=[
                ChatMessage(role="user", content="ЖК Амурский парк"),
                ChatMessage(role="assistant", content="ok"),
            ],
        )
        chunks = []
        async for chunk_data in chat_service.chat_stream(request, "test_user"):
            if chunk_data.startswith("data: "):
                chunk = json.loads(chunk_data[6:])
                chunks.append(ChatStreamChunk(**chunk))

    types = [c.type for c in chunks]
    assert "reformulate" not in types
    chat_service.query_reformulator.reformulate_query.assert_not_called()
    search_call = mock_client.search.await_args
    assert search_call is not None
    search_req = search_call.args[0]
    assert search_req.q == canonical_q


@pytest.mark.asyncio
async def test_chat_stream_error_handling(chat_service):
    with patch("app.chat.get_search_client") as mock_get_client:
        mock_client = Mock()
        mock_client.search = AsyncMock(side_effect=Exception("Search error"))
        mock_get_client.return_value = mock_client

        request = ChatRequest(q="test query", model_id="gpt-5")
        chunks = []
        async for chunk_data in chat_service.chat_stream(request, "test_user"):
            if chunk_data.startswith("data: "):
                chunk = json.loads(chunk_data[6:])
                chunks.append(ChatStreamChunk(**chunk))

        error_chunks = [c for c in chunks if c.type == "error"]
        assert error_chunks and "error" in error_chunks[0].content.lower()


def test_chat_stream_chunk_model_validation():
    chunk = ChatStreamChunk(type="content", content="Hello")
    assert chunk.type == "content" and chunk.content == "Hello"

    chunk = ChatStreamChunk(
        type="citations",
        citations=[{"id": "1", "chat_id": "-123", "message_id": 456, "chunk_idx": 0}],
    )
    assert chunk.type == "citations" and len(chunk.citations) == 1
