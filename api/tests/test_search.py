"""Tests for the Vespa search client context expansion pipeline."""

from __future__ import annotations

import json
import logging
import re
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
    count_significant_query_tokens,
    extract_head_term,
    is_short_lexical_query,
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
            timestamp_ms=1695759000000 + idx * 1000,
        )
        for idx in range(total_seeds)
    ]

    mock_http.post.return_value = async_response({"root": {"children": seeds}})

    def _fake_candidate(seed, trace: bool = False):
        date_seconds = None
        if seed.message_date_ms is not None:
            date_seconds = seed.message_date_ms // 1000
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
            message_date=date_seconds,
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
    expected_score_set = {100 - idx for idx in range(expected_limit)}
    assert {res.seed_score for res in results} == expected_score_set
    # Top `expected_limit` hits by score are message_id 0..expected_limit-1; show newest first.
    assert [res.message_id for res in results] == list(
        range(expected_limit - 1, -1, -1)
    )


@pytest.mark.asyncio
async def test_results_slot_by_score_display_by_recency(
    search_client: VespaSearchClient,
    mock_http: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "search_seed_limit", 5)
    monkeypatch.setattr(settings, "search_default_limit", 4)

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
        date_seconds = None
        if seed.message_date_ms is not None:
            date_seconds = seed.message_date_ms // 1000
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
            message_date=date_seconds,
        )

    monkeypatch.setattr(
        search_client,
        "_build_candidate",
        AsyncMock(side_effect=_fake_candidate),
    )

    results = await search_client.search(SearchRequest(q="ordering", limit=4))

    ordered_ids = [res.id for res in results]
    assert len(results) == 4
    assert ordered_ids == [
        seeds[3]["fields"]["id"],
        seeds[2]["fields"]["id"],
        seeds[1]["fields"]["id"],
        seeds[0]["fields"]["id"],
    ]


@pytest.mark.asyncio
async def test_strictly_newer_low_score_does_not_replace_slot(
    search_client: VespaSearchClient,
    mock_http: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "search_seed_limit", 5)
    monkeypatch.setattr(settings, "search_default_limit", 2)

    base_ts = 1700000000000
    seeds = [
        make_seed(
            "chat-x",
            1,
            text="older strong",
            score=0.9,
            timestamp_ms=base_ts,
        ),
        make_seed(
            "chat-x",
            2,
            text="newer weak",
            score=0.2,
            timestamp_ms=base_ts + 50_000,
        ),
        make_seed(
            "chat-x",
            3,
            text="newest weak",
            score=0.15,
            timestamp_ms=base_ts + 100_000,
        ),
    ]

    mock_http.post.return_value = async_response({"root": {"children": seeds}})

    def _fake_candidate(seed, trace: bool = False):
        date_seconds = None
        if seed.message_date_ms is not None:
            date_seconds = seed.message_date_ms // 1000
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
            message_date=date_seconds,
        )

    monkeypatch.setattr(
        search_client,
        "_build_candidate",
        AsyncMock(side_effect=_fake_candidate),
    )

    results = await search_client.search(SearchRequest(q="slot", limit=2))
    assert [r.message_id for r in results] == [2, 1]
    assert [r.seed_score for r in results] == [0.2, 0.9]


@pytest.mark.asyncio
async def test_single_result_keeps_highest_score_over_newer_weaker(
    search_client: VespaSearchClient,
    mock_http: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "search_seed_limit", 5)
    monkeypatch.setattr(settings, "search_default_limit", 1)

    base_ts = 1700000000000
    seeds = [
        make_seed(
            "chat-x",
            1,
            text="older strong",
            score=0.9,
            timestamp_ms=base_ts,
        ),
        make_seed(
            "chat-x",
            2,
            text="newer weak",
            score=0.2,
            timestamp_ms=base_ts + 60_000,
        ),
    ]

    mock_http.post.return_value = async_response({"root": {"children": seeds}})

    def _fake_candidate(seed, trace: bool = False):
        date_seconds = None
        if seed.message_date_ms is not None:
            date_seconds = seed.message_date_ms // 1000
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
            message_date=date_seconds,
        )

    monkeypatch.setattr(
        search_client,
        "_build_candidate",
        AsyncMock(side_effect=_fake_candidate),
    )

    results = await search_client.search(SearchRequest(q="one", limit=1))
    assert len(results) == 1
    assert results[0].message_id == 1
    assert results[0].seed_score == pytest.approx(0.9)


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
    formatted_text = "[2020-01-01 00:00 • Test User] Sample message about a place"
    timestamp_ms = 1577836800000  # 2020-01-01 00:00:00 UTC
    seed_payload = {
        "root": {
            "children": [
                make_seed(
                    "chat-4",
                    200,
                    text=formatted_text,
                    score=0.87,
                    timestamp_ms=timestamp_ms,
                    sender="Test User",
                    sender_username="testuser",
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
                    timestamp_ms=timestamp_ms,
                    sender="Test User",
                    sender_username="testuser",
                )
            ]
        }
    }

    mock_http.post.side_effect = [
        async_response(seed_payload),
        async_response(neighbor_payload),
    ]

    req = SearchRequest(q="place", hybrid=False, limit=1)
    results = await search_client.search(req)

    assert len(results) == 1
    mock_embedder.embed.assert_not_called()

    line = results[0].text.splitlines()[0]
    assert line == formatted_text
    assert line.count("[2020-01-01 00:00") == 1


def async_response(payload: dict[str, Any]):
    class _Response:
        def __init__(self, data: dict[str, Any]):
            self._data = data

        def json(self) -> dict[str, Any]:
            return self._data

        def raise_for_status(self) -> None:  # pragma: no cover - no-op
            return None

    return _Response(payload)


@pytest.mark.asyncio
async def test_build_query_uses_small_vectors_for_1536_dimensions(
    search_client: VespaSearchClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "embed_dimensions", 1536)
    monkeypatch.setattr(settings, "embed_model", "BAAI/bge-en-icl")
    req = SearchRequest(q="hello", hybrid=True, limit=5)
    _yql, body, _params = await search_client._build_query(req)
    assert body["ranking"] == "hybrid-small"
    assert "input.query(qv_small)" in body


def test_prepare_bm25_query_russian_uses_ru_language(
    search_client: VespaSearchClient,
) -> None:
    _, lang = search_client._prepare_bm25_query("рекомендации хоумстейджеров")
    assert lang == "ru"


def test_prepare_bm25_query_ukrainian_uses_uk_language(
    search_client: VespaSearchClient,
) -> None:
    _, lang = search_client._prepare_bm25_query("щось про їжаків у лісі")
    assert lang == "uk"


def test_count_significant_tokens_and_short_query_heuristic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "search_short_query_max_significant_tokens", 3)
    assert is_short_lexical_query("hello") is False
    assert count_significant_query_tokens("хоумстейджеры") == 1
    assert is_short_lexical_query("хоумстейджеры") is True
    assert count_significant_query_tokens("рекомендации хоумстейджеров") == 2
    assert is_short_lexical_query("рекомендации хоумстейджеров") is True
    long_ru = "первый второй третий четвертый пятый запрос про хоумстейджеров"
    assert count_significant_query_tokens(long_ru) >= 4
    assert is_short_lexical_query(long_ru) is False


@pytest.mark.asyncio
async def test_build_query_short_lexical_and_rank_profile(
    search_client: VespaSearchClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "embed_dimensions", 1536)
    monkeypatch.setattr(settings, "search_short_query_max_significant_tokens", 3)
    req = SearchRequest(q="рекомендации хоумстейджеров", hybrid=True, limit=8)
    yql, body, _params = await search_client._build_query(req)
    assert body["ranking"] == "hybrid-small-short"
    assert "input.query(qv_small)" in body
    assert "nearestNeighbor" in yql
    assert " and " in yql
    assert "userInput(@q)" in yql


@pytest.mark.asyncio
async def test_build_query_short_lexical_relaxed_uses_or_fusion(
    search_client: VespaSearchClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "embed_dimensions", 1536)
    monkeypatch.setattr(settings, "search_short_query_max_significant_tokens", 3)
    req = SearchRequest(q="рекомендации хоумстейджеров", hybrid=True, limit=8)
    yql, body, _params = await search_client._build_query(
        req, relax_short_lexical_and=True
    )
    assert body["ranking"] == "hybrid-small-short"
    assert "input.query(qv_small)" in body
    assert "nearestNeighbor" in yql
    assert " or " in yql
    assert "userInput(@q)" in yql
    assert " and (userInput" not in yql


@pytest.mark.asyncio
async def test_build_query_long_query_uses_standard_hybrid_or(
    search_client: VespaSearchClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "embed_dimensions", 1536)
    monkeypatch.setattr(settings, "search_short_query_max_significant_tokens", 3)
    req = SearchRequest(
        q="первый второй третий четвертый хоумстейджер",
        hybrid=True,
        limit=5,
    )
    yql, body, _params = await search_client._build_query(req)
    assert body["ranking"] == "hybrid-small"
    assert " or " in yql


HOMESTAGER_CANONICAL_QUERY = "посоветуйте хоумстейджера"
_HOMESTAGER_TERM_RE = re.compile(r"хоумстейджер", re.IGNORECASE)


def test_extract_head_term_homestager_imperative() -> None:
    assert extract_head_term(HOMESTAGER_CANONICAL_QUERY) == "хоумстейджер"
    assert extract_head_term("посоветуйте сантехника") == "сантехника"


def test_homestager_canonical_query_classified_as_short_lexical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Canonical chat incident: two significant tokens → short lexical pipeline."""
    monkeypatch.setattr(settings, "search_short_query_max_significant_tokens", 3)
    assert count_significant_query_tokens(HOMESTAGER_CANONICAL_QUERY) == 2
    assert is_short_lexical_query(HOMESTAGER_CANONICAL_QUERY) is True


@pytest.mark.asyncio
async def test_build_query_homestager_canonical_strict_and_short_rank(
    search_client: VespaSearchClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "embed_dimensions", 1536)
    monkeypatch.setattr(settings, "search_short_query_max_significant_tokens", 3)
    req = SearchRequest(q=HOMESTAGER_CANONICAL_QUERY, hybrid=True, limit=10)
    yql, body, _params = await search_client._build_query(req)
    assert body["ranking"] == "hybrid-small-short"
    assert body["q"] == "хоумстейджер"
    assert body.get("input.language") == "ru"
    assert "nearestNeighbor" in yql
    assert " and " in yql
    assert "userInput(@q)" in yql
    embedder = search_client.embedder
    assert isinstance(embedder, AsyncMock)
    embedder.embed.assert_awaited_once_with(HOMESTAGER_CANONICAL_QUERY)


def _homestager_neighbor_payload(chat_id: str, message_id: int, text: str) -> dict:
    return {
        "root": {
            "children": [
                make_message(
                    chat_id,
                    message_id,
                    text=text,
                    timestamp_ms=1_700_000_000_000,
                )
            ]
        }
    }


@pytest.mark.asyncio
async def test_homestager_canonical_relaxed_catches_lexical_seed(
    search_client: VespaSearchClient,
    mock_http: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Vespa OR fusion returns a lexical seed, the pipeline surfaces хоумстейджер."""
    monkeypatch.setattr(settings, "embed_dimensions", 1536)
    monkeypatch.setattr(settings, "search_short_query_max_significant_tokens", 3)
    chat_id = "10001"
    lexical_text = (
        "Synthetic: могу порекомендовать хоумстейджера, писать в личку testuser."
    )
    strict_empty = {"root": {"children": []}}
    relaxed_seeds = {
        "root": {
            "children": [
                make_seed(
                    chat_id,
                    42,
                    text=lexical_text,
                    score=12.0,
                    timestamp_ms=1_700_000_000_000,
                    source_title="Synthetic",
                )
            ]
        }
    }
    supplement_lexical = {
        "root": {
            "children": [
                make_seed(
                    chat_id,
                    42,
                    text=lexical_text,
                    score=14.0,
                    timestamp_ms=1_700_000_000_000,
                )
            ]
        }
    }
    mock_http.post.side_effect = [
        async_response(strict_empty),
        async_response(relaxed_seeds),
        async_response(supplement_lexical),
        async_response(_homestager_neighbor_payload(chat_id, 42, lexical_text)),
    ]
    req = SearchRequest(q=HOMESTAGER_CANONICAL_QUERY, hybrid=True, limit=5)
    results = await search_client.search(req)
    assert mock_http.post.await_count == 4
    first_body = mock_http.post.await_args_list[0].kwargs["json"]
    second_body = mock_http.post.await_args_list[1].kwargs["json"]
    assert " and " in first_body["yql"]
    assert " or " in second_body["yql"]
    assert len(results) == 1
    assert _HOMESTAGER_TERM_RE.search(results[0].text)


@pytest.mark.asyncio
async def test_homestager_canonical_lexical_supplement_overrides_semantic_noise(
    search_client: VespaSearchClient,
    mock_http: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BM25 supplement on head-term surfaces homestager when hybrid OR is noise."""
    monkeypatch.setattr(settings, "embed_dimensions", 1536)
    monkeypatch.setattr(settings, "search_short_query_max_significant_tokens", 3)
    chat_id = "10001"
    noise_text = "Synthetic: обсуждаем ЖК Тестовый-1, сдача в 2027, ипотека."
    lexical_text = "Synthetic: рекомендую хоумстейджер testuser https://t.me/example"
    strict_empty = {"root": {"children": []}}
    relaxed_seeds = {
        "root": {
            "children": [
                make_seed(
                    chat_id,
                    99,
                    text=noise_text,
                    score=25.0,
                    timestamp_ms=1_800_000_000_000,
                    source_title="Synthetic",
                )
            ]
        }
    }
    supplement_lexical = {
        "root": {
            "children": [
                make_seed(
                    chat_id,
                    42,
                    text=lexical_text,
                    score=20.0,
                    timestamp_ms=1_700_000_000_000,
                )
            ]
        }
    }
    mock_http.post.side_effect = [
        async_response(strict_empty),
        async_response(relaxed_seeds),
        async_response(supplement_lexical),
        async_response(_homestager_neighbor_payload(chat_id, 42, lexical_text)),
    ]
    req = SearchRequest(q=HOMESTAGER_CANONICAL_QUERY, hybrid=True, limit=5)
    results = await search_client.search(req)
    assert len(results) == 1
    assert _HOMESTAGER_TERM_RE.search(results[0].text)


@pytest.mark.asyncio
async def test_short_lexical_score_first_not_recency(
    search_client: VespaSearchClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Short lexical final slice keeps score order, not newest-first."""
    monkeypatch.setattr(settings, "search_short_query_max_significant_tokens", 3)
    monkeypatch.setattr(settings, "search_short_lexical_seed_cap", 2)
    monkeypatch.setattr(settings, "search_lexical_supplement_hits", 2)
    mock_http = search_client.http
    assert isinstance(mock_http, AsyncMock)

    high_score_old = make_seed(
        "10001",
        1,
        text="Synthetic: хоумстейджер contact",
        score=30.0,
        timestamp_ms=1_600_000_000_000,
    )
    low_score_new = make_seed(
        "10001",
        2,
        text="Synthetic: посоветуйте плиточника",
        score=10.0,
        timestamp_ms=1_900_000_000_000,
    )
    hybrid_hits = {"root": {"children": [low_score_new, high_score_old]}}
    supplement = {"root": {"children": [high_score_old]}}
    neighbor = lambda mid, txt: async_response(
        _homestager_neighbor_payload("10001", mid, txt)
    )

    mock_http.post.side_effect = [
        async_response(hybrid_hits),
        async_response(supplement),
        neighbor(1, high_score_old["fields"]["text"]),
        neighbor(2, low_score_new["fields"]["text"]),
    ]

    req = SearchRequest(q="посоветуйте хоумстейджера", hybrid=True, limit=1)
    results = await search_client.search(req)
    assert len(results) == 1
    assert results[0].message_id == 1


def test_merge_lexical_first_seeds_prioritises_head_term(
    search_client: VespaSearchClient,
) -> None:
    lexical = SeedHit(
        id="1:1",
        chat_id="1",
        message_id=1,
        message_date_ms=1,
        text="Synthetic хоумстейджер link",
        score=5.0,
        fields={},
    )
    noise = SeedHit(
        id="1:2",
        chat_id="1",
        message_id=2,
        message_date_ms=2,
        text="Посоветуйте плиточника",
        score=99.0,
        fields={},
    )
    merged = search_client._merge_lexical_first_seeds(
        [noise], [lexical], head_term="хоумстейджер"
    )
    assert merged[0].message_id == 1
