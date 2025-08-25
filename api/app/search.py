"""Search endpoint and utilities for querying Vespa."""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .settings import settings

router = APIRouter()


# ---------------------------------------------------------------------------
# Simple LRU cache with TTL for query embeddings
# ---------------------------------------------------------------------------


class _LRUCache:
    def __init__(self, maxsize: int, ttl: int):
        self.maxsize = maxsize
        self.ttl = ttl
        self.store: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        now = time.time()
        if key in self.store:
            ts, value = self.store[key]
            if now - ts < self.ttl:
                self.store.move_to_end(key)
                return value
            del self.store[key]
        return None

    def set(self, key: str, value: Any) -> None:
        now = time.time()
        self.store[key] = (now, value)
        self.store.move_to_end(key)
        if len(self.store) > self.maxsize:
            self.store.popitem(last=False)


_embed_cache = _LRUCache(
    settings.query_embed_cache_size, settings.query_embed_cache_ttl_sec
)


async def embed_query(text: str, model_id: str) -> List[float]:
    """Deterministic stub embedding.

    The real project would call OpenAI here, but for tests and offline
    environments we generate a pseudo vector based on SHA256 of the input.
    """

    if settings.openai_stub:
        digest = hashlib.sha256(f"{model_id}:{text}".encode()).digest()
        # produce 3 floats between 0 and 1
        return [
            int.from_bytes(digest[i : i + 4], "big") / 2**32 for i in range(0, 12, 4)
        ]
    # In real deployments, call OpenAI here. For now raise to avoid silent
    # network requests during tests.
    raise RuntimeError("Real embedding not implemented in test environment")


async def embed_query_cached(text: str, model_id: str) -> List[float]:
    key = f"{model_id}:{text}"
    cached = _embed_cache.get(key)
    if cached is not None:
        return cached
    vec = await embed_query(text, model_id)
    _embed_cache.set(key, vec)
    return vec


# ---------------------------------------------------------------------------
# Pydantic models for request/response
# ---------------------------------------------------------------------------


class SearchFilters(BaseModel):
    chat_ids: Optional[List[str]] = None
    chat_type: Optional[str] = None
    sender_username: Optional[str] = None
    date_from: Optional[str] = None  # ISO8601 date
    date_to: Optional[str] = None
    has_link: Optional[bool] = None


class SearchRequest(BaseModel):
    q: str = ""
    k: int = Field(default_factory=lambda: settings.search_default_limit)
    offset: int = 0
    sort: str = "relevance"
    model_label: Optional[str] = None
    filters: SearchFilters = Field(default_factory=SearchFilters)
    debug: bool = False


# ---------------------------------------------------------------------------
# YQL builder
# ---------------------------------------------------------------------------


def _date_to_epoch(date_str: str | None) -> int | None:
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str)
        return int(dt.timestamp())
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_date")


def build_yql(req: SearchRequest, has_vector: bool) -> str:
    tokens: List[str] = [t for t in req.q.split() if t]
    nn_clause = ""
    lexical_clause = ""
    if has_vector:
        nn_clause = '([{"targetHits":100}]nearestNeighbor(vector, q_vec))'
    if tokens:
        terms = " OR ".join(f'default contains "{t}"' for t in tokens)
        lexical_clause = f"weakAnd({terms})"
    if nn_clause and lexical_clause:
        base = f"({nn_clause} OR {lexical_clause})"
    else:
        base = nn_clause or lexical_clause or "true"

    filters = []
    if req.filters.chat_ids:
        ids = ",".join(f'"{cid}"' for cid in req.filters.chat_ids)
        filters.append(f"chat_id in [{ids}]")
    if req.filters.chat_type:
        filters.append(f'(chat_type contains "{req.filters.chat_type}")')
    if req.filters.sender_username:
        filters.append(f'(sender_username contains "{req.filters.sender_username}")')
    df = _date_to_epoch(req.filters.date_from)
    dt = _date_to_epoch(req.filters.date_to)
    if df is not None or dt is not None:
        lo = df if df is not None else 0
        hi = dt if dt is not None else 4102444800  # year 2100
        filters.append(f"(message_date >= {lo} AND message_date <= {hi})")
    if req.filters.has_link is not None:
        val = "true" if req.filters.has_link else "false"
        filters.append(f"(has_link contains {val})")
    filters.append("( (not hasField(deleted_at)) OR (deleted_at = 0) )")

    where = base
    if filters:
        where = f"{where} AND " + " AND ".join(filters)

    return f"select * from sources chunk where {where} | limit {req.k} | offset {req.offset};"


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------


@router.post("/search")
async def search(req: SearchRequest):
    # Validate q/filters rules
    if req.sort != "recency" and not req.q:
        raise HTTPException(status_code=400, detail="q_required")
    if req.sort == "recency" and not req.q:
        if not any(
            [
                req.filters.chat_ids,
                req.filters.chat_type,
                req.filters.sender_username,
                req.filters.date_from,
                req.filters.date_to,
                req.filters.has_link is not None,
            ]
        ):
            raise HTTPException(status_code=400, detail="q_or_filter_required")

    if req.k <= 0:
        req.k = settings.search_default_limit
    if req.k > settings.search_max_limit:
        req.k = settings.search_max_limit

    model_map = settings.model_map
    model_id = model_map.get(req.model_label or "", None)
    if model_id is None:
        # use first model as default
        model_id = next(iter(model_map.values()))

    vector: List[float] | None = None
    if req.q:
        vector = await embed_query_cached(req.q, model_id)

    yql = build_yql(req, vector is not None)
    rank_profile = req.sort

    result = {
        "total": 0,
        "offset": req.offset,
        "limit": req.k,
        "sort": req.sort,
        "hits": [],
    }

    if req.debug:
        result["debug"] = {
            "vespa_query": yql,
            "rank_profile": rank_profile,
            "timing_ms": 0,
        }

    return result


__all__ = [
    "router",
    "SearchRequest",
    "SearchFilters",
    "embed_query",
    "embed_query_cached",
    "build_yql",
]
