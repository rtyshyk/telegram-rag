"""Tests for the Vespa search client context expansion pipeline."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock

import pytest

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from app.search import (
    SearchRequest,
    SearchResult,
    SearchSpan,
    SeedHit,
    VespaSearchClient,
)
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


def test_seed_dedupe_keeps_highest_scoring_within_gap(
    mock_http: AsyncMock,
    mock_embedder: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "search_seed_dedupe_message_gap", 5)
    monkeypatch.setattr(settings, "search_seed_dedupe_time_gap_seconds", 0)

    client = VespaSearchClient(http=mock_http)
    client.embedder = mock_embedder

    seeds = [
        SeedHit(
            id="chat:high-score",
            chat_id="chat",
            message_id=100,
            message_date_ms=1_600_000_000_000,
            text="Older high score",
            score=50.0,
            fields={"message_date": 1_600_000_000_000},
        ),
        SeedHit(
            id="chat:recent-lower",
            chat_id="chat",
            message_id=103,
            message_date_ms=1_700_000_000_000,
            text="Recent lower score",
            score=30.0,
            fields={"message_date": 1_700_000_000_000},
        ),
        SeedHit(
            id="chat:far-mid",
            chat_id="chat",
            message_id=120,
            message_date_ms=1_800_000_000_000,
            text="Far mid score",
            score=40.0,
            fields={"message_date": 1_800_000_000_000},
        ),
    ]

    filtered = client._filter_seeds(seeds)
    filtered_ids = [seed.id for seed in filtered]

    assert filtered_ids == ["chat:high-score", "chat:far-mid"]


def test_search_request_expansion_level_clamped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "search_expansion_max_level", 2)
    req_high = SearchRequest(q="x", expansion_level=5)
    assert req_high.expansion_level == 2
    req_low = SearchRequest(q="x", expansion_level=-3)
    assert req_low.expansion_level == 0


@pytest.mark.asyncio
async def test_returns_empty_for_blank_query(
    search_client: VespaSearchClient, mock_http: AsyncMock
) -> None:
    results = await search_client.search(SearchRequest(q="   "))
    assert results == []
    mock_http.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_broaden_raises_result_cap(
    search_client: VespaSearchClient,
    mock_http: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "search_seed_limit", 80)

    total_seeds = (
        settings.search_default_limit + (2 * settings.search_expansion_result_step) + 5
    )
    seeds = [
        make_seed(
            f"chat-{idx}",
            idx,
            text=f"Seed {idx}",
            score=100 - idx,
            timestamp_ms=1695759000000 + idx,
        )
        for idx in range(total_seeds)
    ]

    mock_http.post.return_value = async_response({"root": {"children": seeds}})

    def _fake_candidate(seed, trace: bool = False):
        return SearchResult(
            id=seed.id,
            text=seed.text,
            chat_id=seed.chat_id,
            message_id=seed.message_id,
            score=seed.score,
            seed_score=seed.score,
            retrieval_score=seed.score,
            span=SearchSpan(
                start_id=seed.message_id,
                end_id=seed.message_id,
                start_ts=seed.message_date_ms,
                end_ts=seed.message_date_ms,
            ),
            message_count=1,
        )

    monkeypatch.setattr(
        search_client,
        "_build_candidate",
        AsyncMock(side_effect=_fake_candidate),
    )

    req = SearchRequest(q="broaden me", expansion_level=2)
    results = await search_client.search(req)

    expected_limit = min(
        settings.search_default_limit + (2 * settings.search_expansion_result_step),
        settings.search_context_max_return,
    )
    assert len(results) == expected_limit
    assert [res.seed_score for res in results] == sorted(
        (res.seed_score for res in results), reverse=True
    )


@pytest.mark.asyncio
async def test_results_sorted_by_score_then_recency(
    search_client: VespaSearchClient,
    mock_http: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "search_seed_limit", 5)

    base_ts = 1700000000000
    seeds = [
        make_seed(
            "chat-x",
            1,
            text="older high score",
            score=0.9,
            timestamp_ms=base_ts,
        ),
        make_seed(
            "chat-x",
            2,
            text="newer high score",
            score=0.9,
            timestamp_ms=base_ts + 5000,
        ),
        make_seed(
            "chat-x",
            3,
            text="mid score",
            score=0.7,
            timestamp_ms=base_ts + 10000,
        ),
        make_seed(
            "chat-x",
            4,
            text="low score",
            score=0.2,
            timestamp_ms=base_ts + 15000,
        ),
    ]

    mock_http.post.return_value = async_response({"root": {"children": seeds}})

    def _fake_candidate(seed, trace: bool = False):
        return SearchResult(
            id=seed.id,
            text=seed.text,
            chat_id=seed.chat_id,
            message_id=seed.message_id,
            score=seed.score,
            seed_score=seed.score,
            retrieval_score=seed.score,
            span=SearchSpan(
                start_id=seed.message_id,
                end_id=seed.message_id,
                start_ts=seed.message_date_ms,
                end_ts=seed.message_date_ms,
            ),
            message_count=1,
        )

    monkeypatch.setattr(
        search_client,
        "_build_candidate",
        AsyncMock(side_effect=_fake_candidate),
    )

    results = await search_client.search(SearchRequest(q="ordering"))

    ordered_ids = [res.id for res in results]
    assert ordered_ids[:3] == [
        seeds[1]["fields"]["id"],
        seeds[0]["fields"]["id"],
        seeds[2]["fields"]["id"],
    ]


@pytest.mark.asyncio
async def test_trace_logging_emits_stages(
    search_client: VespaSearchClient,
    mock_http: AsyncMock,
    mock_embedder: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(settings, "search_seed_limit", 2)

    seed_payload = {
        "root": {
            "children": [
                make_seed(
                    "chat-trace",
                    1,
                    text="Seed message",
                    score=0.9,
                    timestamp_ms=1700000000000,
                )
            ]
        }
    }
    neighbor_payload = {
        "root": {
            "children": [
                make_message(
                    "chat-trace",
                    1,
                    text="Neighbor context",
                    timestamp_ms=1700000001000,
                )
            ]
        }
    }

    mock_http.post.side_effect = [
        async_response(seed_payload),
        async_response(neighbor_payload),
    ]

    caplog.set_level(logging.DEBUG)
    await search_client.search(SearchRequest(q="trace", trace=True))

    stages: list[str] = []
    for record in caplog.records:
        if record.levelno != logging.DEBUG:
            continue
        try:
            payload = json.loads(record.message)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        stage_name = payload.get("stage")
        if isinstance(stage_name, str):
            stages.append(stage_name)

    expected_stages = {
        "vespa_results",
        "seed_list",
        "seed_list_deduped",
        "rerank_results",
        "gpt_context",
    }

    assert set(stages) == expected_stages


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
