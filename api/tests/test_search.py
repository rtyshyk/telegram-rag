"""Tests for the Vespa search client context expansion pipeline."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock

import pytest

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from app.search import SearchRequest, SearchResult, VespaSearchClient
from app.settings import settings


@pytest.fixture
def mock_http() -> AsyncMock:
    client = AsyncMock()
    client.post = AsyncMock()
    return client


@pytest.fixture
def mock_embedder() -> AsyncMock:
    embedder = AsyncMock()
    embedder.embed = AsyncMock(return_value=[0.1] * 1536)
    return embedder


@pytest.fixture
def search_client(
    mock_http: AsyncMock,
    mock_embedder: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> VespaSearchClient:
    """Construct a VespaSearchClient with deterministic dependencies."""

    monkeypatch.setattr(settings, "rerank_enabled", False)
    monkeypatch.setattr(settings, "voyage_stub", False)
    monkeypatch.setattr(settings, "voyage_api_key", None)
    monkeypatch.setattr(settings, "embed_model", "text-embedding-3-small")
    monkeypatch.setattr(settings, "search_seed_limit", 3)
    monkeypatch.setattr(settings, "search_seeds_per_chat", 2)
    monkeypatch.setattr(settings, "search_neighbor_min_messages", 1)
    monkeypatch.setattr(settings, "search_neighbor_message_window", 2)
    monkeypatch.setattr(settings, "search_neighbor_time_window_minutes", 10)
    monkeypatch.setattr(settings, "search_candidate_max_messages", 10)
    monkeypatch.setattr(settings, "search_candidate_token_limit", 200)
    monkeypatch.setattr(settings, "search_seed_dedupe_message_gap", 0)
    monkeypatch.setattr(settings, "search_seed_dedupe_time_gap_seconds", 0)

    client = VespaSearchClient(http=mock_http)
    client.embedder = mock_embedder
    return client


def make_seed(
    chat_id: str,
    message_id: int,
    *,
    text: str,
    score: float,
    timestamp_ms: Optional[int] = None,
    **extra: Any,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "id": f"{chat_id}:{message_id}",
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
    }
    if timestamp_ms is not None:
        fields["message_date"] = timestamp_ms
    fields.update(extra)
    return {"fields": fields, "relevance": score}


def make_message(
    chat_id: str,
    message_id: int,
    *,
    text: str,
    timestamp_ms: Optional[int] = None,
    **extra: Any,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "id": f"{chat_id}:{message_id}",
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
    }
    if timestamp_ms is not None:
        fields["message_date"] = timestamp_ms
    fields.update(extra)
    return {"fields": fields}


@pytest.mark.asyncio
async def test_returns_empty_for_blank_query(
    search_client: VespaSearchClient, mock_http: AsyncMock
) -> None:
    results = await search_client.search(SearchRequest(q="   "))
    assert results == []
    mock_http.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_hybrid_context_expansion(
    search_client: VespaSearchClient,
    mock_http: AsyncMock,
    mock_embedder: AsyncMock,
) -> None:
    seed_payload = {
        "root": {
            "children": [
                make_seed(
                    "chat-1",
                    101,
                    text="Reminder about the flight",
                    score=0.92,
                    timestamp_ms=1695759000000,
                    sender="Alex",
                    chat_username="travel-group",
                    source_title="Itinerary",
                )
            ]
        }
    }
    neighbor_payload = {
        "root": {
            "children": [
                make_message(
                    "chat-1",
                    100,
                    text="Let's meet before the flight.",
                    timestamp_ms=1695758940000,
                    sender="Jamie",
                ),
                make_message(
                    "chat-1",
                    101,
                    text="Reminder about the flight",
                    timestamp_ms=1695759000000,
                    sender="Alex",
                ),
                make_message(
                    "chat-1",
                    102,
                    text="Flight is at 11:34 tomorrow.",
                    timestamp_ms=1695759060000,
                    sender="Jamie",
                ),
            ]
        }
    }
    mock_http.post.side_effect = [
        async_response(seed_payload),
        async_response(neighbor_payload),
    ]

    req = SearchRequest(q="flight 11:34", hybrid=True, limit=3)
    results = await search_client.search(req)

    assert len(results) == 1
    result = results[0]
    assert isinstance(result, SearchResult)
    assert result.chat_id == "chat-1"
    assert result.message_id == 101
    assert result.message_count == 3
    assert result.span.start_id == 100
    assert result.span.end_id == 102
    assert "Flight is at 11:34 tomorrow." in result.text
    assert result.seed_score == pytest.approx(0.92)
    assert result.retrieval_score == pytest.approx(0.92)
    assert result.chat_username == "travel-group"
    assert result.source_title == "Itinerary"

    assert mock_http.post.await_count == 2
    body = mock_http.post.await_args_list[0].kwargs["json"]
    assert body["hits"] == settings.search_seed_limit
    assert "nearestNeighbor" in body["yql"]
    mock_embedder.embed.assert_awaited_once_with("flight 11:34")


@pytest.mark.asyncio
async def test_bm25_only_when_hybrid_false(
    search_client: VespaSearchClient,
    mock_http: AsyncMock,
    mock_embedder: AsyncMock,
) -> None:
    seed_payload = {
        "root": {
            "children": [
                make_seed(
                    "chat-2",
                    10,
                    text="Keyword seed",
                    score=0.4,
                    timestamp_ms=1695755000000,
                )
            ]
        }
    }
    neighbor_payload = {
        "root": {
            "children": [
                make_message(
                    "chat-2",
                    10,
                    text="Keyword context",
                    timestamp_ms=1695755000000,
                )
            ]
        }
    }
    mock_http.post.side_effect = [
        async_response(seed_payload),
        async_response(neighbor_payload),
    ]

    req = SearchRequest(q="keyword", hybrid=False, limit=2)
    results = await search_client.search(req)

    assert len(results) == 1
    mock_embedder.embed.assert_not_called()
    body = mock_http.post.await_args_list[0].kwargs["json"]
    assert body["ranking"] == "default"
    assert not any(key.startswith("input.query(") for key in body)


@pytest.mark.asyncio
async def test_rerank_stub_orders_by_overlap(
    mock_http: AsyncMock,
    mock_embedder: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "embed_model", "text-embedding-3-small")
    monkeypatch.setattr(settings, "rerank_enabled", True)
    monkeypatch.setattr(settings, "voyage_stub", True)
    monkeypatch.setattr(settings, "voyage_api_key", None)
    monkeypatch.setattr(settings, "search_seed_limit", 2)
    monkeypatch.setattr(settings, "search_candidate_max_messages", 5)
    monkeypatch.setattr(settings, "search_neighbor_message_window", 1)
    monkeypatch.setattr(settings, "search_neighbor_min_messages", 1)
    monkeypatch.setattr(settings, "search_seed_dedupe_message_gap", 0)
    monkeypatch.setattr(settings, "search_seed_dedupe_time_gap_seconds", 0)

    client = VespaSearchClient(http=mock_http)
    client.embedder = mock_embedder

    seeds = {
        "root": {
            "children": [
                make_seed(
                    "chat-3",
                    50,
                    text="Lunch tomorrow?",
                    score=0.8,
                    timestamp_ms=1695760000000,
                ),
                make_seed(
                    "chat-3",
                    60,
                    text="Flight reminder",
                    score=0.6,
                    timestamp_ms=1695764000000,
                ),
            ]
        }
    }
    neighbors_lunch = {
        "root": {
            "children": [
                make_message(
                    "chat-3",
                    49,
                    text="Lunch at noon?",
                    timestamp_ms=1695759940000,
                ),
                make_message(
                    "chat-3",
                    50,
                    text="Lunch tomorrow?",
                    timestamp_ms=1695760000000,
                ),
            ]
        }
    }
    neighbors_flight = {
        "root": {
            "children": [
                make_message(
                    "chat-3",
                    59,
                    text="Travel update",
                    timestamp_ms=1695763940000,
                ),
                make_message(
                    "chat-3",
                    60,
                    text="Flight leaves 11:34",
                    timestamp_ms=1695764000000,
                ),
            ]
        }
    }
    mock_http.post.side_effect = [
        async_response(seeds),
        async_response(neighbors_lunch),
        async_response(neighbors_flight),
    ]

    req = SearchRequest(q="flight 11:34", hybrid=True, limit=2)
    results = await client.search(req)

    assert len(results) == 2
    assert results[0].message_id == 60
    assert "11:34" in results[0].text
    assert results[0].score >= results[1].score
    assert results[0].rerank_score is not None


@pytest.mark.asyncio
async def test_cyrillic_query_expansion_injects_variants(
    search_client: VespaSearchClient,
    mock_embedder: AsyncMock,
) -> None:
    req = SearchRequest(q="коли іра прилітає з катовіце?", hybrid=True, limit=5)
    _, body, _ = await search_client._build_query(req)

    assert "прилітаєш" in body["q"]
    assert body.get("input.language") == "uk"
    mock_embedder.embed.assert_awaited_once_with("коли іра прилітає з катовіце?")


@pytest.mark.asyncio
async def test_preserves_single_header_for_formatted_messages(
    search_client: VespaSearchClient,
    mock_http: AsyncMock,
    mock_embedder: AsyncMock,
) -> None:
    formatted_text = "[2025-09-04 06:14 • Iryna Tyshyk] Десь о 13 буду у Катовіце"
    seed_payload = {
        "root": {
            "children": [
                make_seed(
                    "chat-4",
                    200,
                    text=formatted_text,
                    score=0.87,
                    timestamp_ms=1693808040000,
                    sender="Iryna Tyshyk",
                    sender_username="iryna",
                )
            ]
        }
    }
    neighbor_payload = {
        "root": {
            "children": [
                make_message(
                    "chat-4",
                    200,
                    text=formatted_text,
                    timestamp_ms=1693808040000,
                    sender="Iryna Tyshyk",
                    sender_username="iryna",
                )
            ]
        }
    }

    mock_http.post.side_effect = [
        async_response(seed_payload),
        async_response(neighbor_payload),
    ]

    req = SearchRequest(q="катовіце", hybrid=False, limit=1)
    results = await search_client.search(req)

    assert len(results) == 1
    mock_embedder.embed.assert_not_called()

    line = results[0].text.splitlines()[0]
    assert line == formatted_text
    assert line.count("[2025-09-04 06:14") == 1


def async_response(payload: dict[str, Any]):
    class _Response:
        def __init__(self, data: dict[str, Any]):
            self._data = data

        def json(self) -> dict[str, Any]:
            return self._data

        def raise_for_status(self) -> None:  # pragma: no cover - no-op
            return None

    return _Response(payload)
