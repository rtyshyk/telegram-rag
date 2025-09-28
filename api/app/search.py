"""Search utilities: perform hybrid (vector+bm25) search against Vespa."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Dict, List, Optional, Sequence

import httpx
from pydantic import BaseModel, Field, field_validator

from .settings import settings

logger = logging.getLogger(__name__)


class SearchRequest(BaseModel):
    q: str
    limit: int = Field(default=settings.search_default_limit, ge=1)
    chat_id: Optional[str] = None
    thread_id: Optional[int] = None
    hybrid: bool = True
    expansion_level: int = 0
    trace: bool = False

    @field_validator("expansion_level")
    @classmethod
    def _clamp_expansion(cls, value: int) -> int:
        if value < 0:
            return 0
        return min(value, settings.search_expansion_max_level)


class SearchSpan(BaseModel):
    start_id: int
    end_id: int
    start_ts: Optional[int] = None
    end_ts: Optional[int] = None


class SearchResult(BaseModel):
    id: str
    text: str
    chat_id: str
    message_id: int
    chunk_idx: int = 0
    score: float
    seed_score: float
    retrieval_score: Optional[float] = None
    rerank_score: Optional[float] = None
    span: SearchSpan
    message_count: int
    sender: Optional[str] = None
    sender_username: Optional[str] = None
    chat_username: Optional[str] = None
    message_date: Optional[int] = None
    source_title: Optional[str] = None
    chat_type: Optional[str] = None
    edit_date: Optional[int] = None
    thread_id: Optional[int] = None
    has_link: Optional[bool] = None


class ChatInfo(BaseModel):
    chat_id: str
    source_title: Optional[str] = None
    chat_type: Optional[str] = None
    message_count: int = 0


@dataclass
class SeedHit:
    id: str
    chat_id: str
    message_id: int
    message_date_ms: Optional[int]
    text: str
    score: float
    fields: Dict[str, Any]


@dataclass
class MessageRecord:
    message_id: int
    message_date_ms: Optional[int]
    sender: Optional[str]
    sender_username: Optional[str]
    text: str
    source_title: Optional[str]
    chat_type: Optional[str]
    chat_username: Optional[str]
    edit_date: Optional[int]
    thread_id: Optional[int]
    has_link: Optional[bool]
    raw_fields: Dict[str, Any]


class EmbeddingProvider:
    """OpenAI embedding provider."""

    def __init__(self):
        from openai import AsyncOpenAI  # lazy import

        self.model = settings.embed_model
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required")
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def embed(self, text: str) -> List[float]:
        resp = await self.client.embeddings.create(model=self.model, input=[text])
        return resp.data[0].embedding  # type: ignore[attr-defined]


class VoyageReranker:
    """Optional reranker using VoyageAI's Rerank API (or local stub)."""

    _RERANK_ENDPOINT = "https://api.voyageai.com/v1/rerank"

    def __init__(self, http: Optional[httpx.AsyncClient] = None):
        self.stub = bool(settings.voyage_stub)
        self.api_key = settings.voyage_api_key
        self.model = settings.rerank_model
        self.enabled = settings.rerank_enabled and (self.stub or bool(self.api_key))
        self._http = http
        self._owns_http = False

        if self.enabled and not self.stub:
            if self._http is None:
                self._http = httpx.AsyncClient(timeout=20)
                self._owns_http = True
        elif settings.rerank_enabled and not self.enabled:
            logger.warning(
                "Rerank enabled but no Voyage API key provided; falling back to Vespa ranking."
            )

    async def aclose(self) -> None:
        if self._owns_http and self._http:
            await self._http.aclose()

    async def rerank(
        self, query: str, results: List[SearchResult], top_n: int
    ) -> List[SearchResult]:
        if not self.enabled or not results:
            return results[:top_n]

        if not query.strip():
            return results[:top_n]

        if self.stub:
            return self._rerank_stub(query, results, top_n)

        if not self._http or not self.api_key:
            logger.warning("Voyage client not available; skipping rerank.")
            return results[:top_n]

        payload = {
            "model": self.model,
            "query": query,
            "documents": [result.text for result in results],
            "top_k": min(top_n, len(results)),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = await self._http.post(
                self._RERANK_ENDPOINT, json=payload, headers=headers
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # pragma: no cover - network errors
            logger.warning("Voyage rerank failed: %s", exc)
            return results[:top_n]

        reranked: List[SearchResult] = []
        seen_indices: set[int] = set()

        items = data.get("data") or data.get("results", [])

        for item in items:
            idx = item.get("index")
            if idx is None or idx >= len(results):
                continue
            seen_indices.add(idx)
            result = results[idx]
            score_value = item.get("score")
            if score_value is None:
                score_value = item.get("relevance_score", result.score)
            try:
                score = float(score_value)
            except (TypeError, ValueError):
                score = result.score
            result.rerank_score = score
            result.score = score
            reranked.append(result)
            if len(reranked) >= top_n:
                break

        if len(reranked) < top_n:
            for idx, result in enumerate(results):
                if idx in seen_indices:
                    continue
                reranked.append(result)
                if len(reranked) >= top_n:
                    break

        return reranked[:top_n]

    def _rerank_stub(
        self, query: str, results: List[SearchResult], top_n: int
    ) -> List[SearchResult]:
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return results[:top_n]

        scored: List[tuple[float, float, int, SearchResult]] = []
        for idx, result in enumerate(results):
            doc_tokens = self._tokenize(result.text)
            overlap = len(query_tokens & doc_tokens)
            overlap_ratio = overlap / max(len(query_tokens), 1)
            retrieval_score = result.retrieval_score or result.score
            scored.append((overlap_ratio, retrieval_score, idx, result))

        scored.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)

        reranked: List[SearchResult] = []
        seen_indices: set[int] = set()

        for overlap_ratio, _, idx, result in scored:
            if idx in seen_indices:
                continue
            seen_indices.add(idx)
            result.rerank_score = overlap_ratio if overlap_ratio > 0 else None
            if overlap_ratio > 0:
                result.score = overlap_ratio
            reranked.append(result)
            if len(reranked) >= top_n:
                break

        if len(reranked) < top_n:
            for _, _, idx, result in scored:
                if idx in seen_indices:
                    continue
                seen_indices.add(idx)
                reranked.append(result)
                if len(reranked) >= top_n:
                    break

        return reranked[:top_n]

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return {tok for tok in re.findall(r"\w+", text.lower()) if tok}


class VespaSearchClient:
    _CYRILLIC_RE = re.compile(r"[А-Яа-яІіЇїЄєҐґ]")
    _LOG_VECTOR_MARKERS = ("vector", "embedding")
    _TOKEN_RE = re.compile(r"[0-9A-Za-z\u0400-\u04FF]+", re.UNICODE)

    def __init__(self, http: Optional[httpx.AsyncClient] = None):
        self.endpoint = settings.vespa_endpoint.rstrip("/")
        self.http = http or httpx.AsyncClient(timeout=20)
        self.embedder = EmbeddingProvider()
        self.reranker: Optional[VoyageReranker] = None

        if settings.rerank_enabled:
            reranker = VoyageReranker()
            if reranker.enabled:
                self.reranker = reranker

    def _log_stage(self, stage: str, payload: Any | None) -> None:
        if payload is None:
            payload = {}
        serialised = self._serialise_for_log(payload)
        try:
            message = json.dumps(
                {"stage": stage, "payload": serialised},
                ensure_ascii=False,
                indent=2,
            )
        except TypeError:
            message = json.dumps(
                {"stage": stage, "payload": str(serialised)},
                ensure_ascii=False,
                indent=2,
            )
        logger.debug(message)

    def _serialise_for_log(self, value: Any) -> Any:
        if isinstance(value, BaseModel):
            return self._serialise_for_log(value.model_dump())
        if is_dataclass(value):
            return self._serialise_for_log(asdict(value))
        if isinstance(value, dict):
            serialised: Dict[Any, Any] = {}
            for key, val in value.items():
                if (
                    isinstance(key, str)
                    and any(
                        marker in key.lower() for marker in self._LOG_VECTOR_MARKERS
                    )
                    and isinstance(val, (list, tuple, set, dict))
                ):
                    serialised[key] = "[redacted vector]"
                    continue
                serialised[key] = self._serialise_for_log(val)
            return serialised
        if isinstance(value, (list, tuple, set)):
            return [self._serialise_for_log(v) for v in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    async def close(self):
        await self.http.aclose()
        if self.reranker:
            await self.reranker.aclose()

    async def search(self, req: SearchRequest) -> List[SearchResult]:
        query = req.q.strip()
        if not query:
            return []

        expansion_level = max(
            0, min(req.expansion_level, settings.search_expansion_max_level)
        )

        base_limit = max(1, min(req.limit, settings.search_context_max_return))
        if expansion_level > 0 and req.limit == settings.search_default_limit:
            expanded_limit = base_limit + (
                expansion_level * settings.search_expansion_result_step
            )
            final_limit = min(expanded_limit, settings.search_context_max_return)
        else:
            final_limit = base_limit

        base_seed_limit = settings.search_seed_limit
        seed_limit = max(
            final_limit,
            base_seed_limit + expansion_level * settings.search_expansion_seed_step,
        )

        seed_request = (
            req
            if seed_limit == req.limit
            else req.model_copy(update={"limit": seed_limit})
        )

        _, body, _ = await self._build_query(seed_request)

        try:
            data = await self._execute_search(body)
        except Exception as exc:
            logger.error("Vespa search error: %s", exc)
            return []
        root = data.get("root", {}) or {}
        raw_hits = root.get("children", []) or []
        self._log_stage("vespa_results", {"raw_hits": raw_hits})

        seed_hits = self._parse_seed_hits(raw_hits)
        self._log_stage("seed_list", {"seeds": seed_hits})

        filtered_seeds = self._filter_seeds(seed_hits)
        self._log_stage("seed_list_deduped", {"seeds": filtered_seeds})

        if not filtered_seeds:
            rerank_status = bool(self.reranker and self.reranker.enabled)
            self._log_stage(
                "rerank_results",
                {"rerank_enabled": rerank_status, "results": []},
            )
            self._log_stage("gpt_context", [])
            return []

        expand_tasks = [self._build_candidate(seed) for seed in filtered_seeds]
        expanded = await asyncio.gather(*expand_tasks, return_exceptions=True)

        candidates: List[SearchResult] = []
        for seed, result in zip(filtered_seeds, expanded):
            if isinstance(result, Exception):
                logger.warning(
                    "Context expansion failed for %s:%s → %s",
                    seed.chat_id,
                    seed.message_id,
                    result,
                )
                continue
            if result is None:
                continue
            candidates.append(result)

        if not candidates:
            rerank_status = bool(self.reranker and self.reranker.enabled)
            self._log_stage(
                "rerank_results",
                {"rerank_enabled": rerank_status, "results": []},
            )
            self._log_stage("gpt_context", [])
            return []

        candidates.sort(
            key=lambda c: (
                c.message_date or 0,
                c.seed_score,
            ),
            reverse=True,
        )

        reranker = self.reranker
        rerank_enabled = bool(reranker and reranker.enabled)
        if rerank_enabled:
            rerank_cap = max(
                final_limit,
                settings.rerank_candidate_limit
                + expansion_level * settings.search_expansion_rerank_step,
            )
            limited_candidates = candidates[:rerank_cap]
            rerank_results = await reranker.rerank(
                query, limited_candidates, final_limit
            )
        else:
            rerank_results = candidates

        self._log_stage(
            "rerank_results",
            {"rerank_enabled": rerank_enabled, "results": rerank_results},
        )

        final_candidates = rerank_results[:final_limit]
        self._log_stage(
            "gpt_context",
            [
                {
                    "chat_id": result.chat_id,
                    "message_id": result.message_id,
                    "text": result.text,
                    "span": result.span.model_dump(),
                    "score": result.score,
                    "seed_score": result.seed_score,
                    "rerank_score": result.rerank_score,
                }
                for result in final_candidates
            ],
        )
        return final_candidates

    async def _execute_search(self, body: Dict[str, Any]) -> Dict[str, Any]:
        resp = await self.http.post(f"{self.endpoint}/search/", json=body)
        resp.raise_for_status()
        return resp.json()

    def _parse_seed_hits(
        self, hits: Optional[Sequence[Dict[str, Any]]]
    ) -> List[SeedHit]:
        if not hits:
            return []

        seeds: List[SeedHit] = []
        for hit in hits:
            fields = hit.get("fields", {}) or {}
            chat_id = fields.get("chat_id")
            message_id = self._coerce_int(fields.get("message_id"))
            if not chat_id or message_id is None:
                continue
            score_value = hit.get("relevance", 0.0)
            try:
                score = float(score_value)
            except (TypeError, ValueError):
                score = 0.0
            message_date_ms = self._coerce_epoch_ms(fields.get("message_date"))
            text = self._safe_text(fields.get("text"))
            seeds.append(
                SeedHit(
                    id=fields.get("id") or f"{chat_id}:{message_id}",
                    chat_id=chat_id,
                    message_id=message_id,
                    message_date_ms=message_date_ms,
                    text=text,
                    score=score,
                    fields=fields,
                )
            )

        return seeds

    def _filter_seeds(self, seeds: Sequence[SeedHit]) -> List[SeedHit]:
        if not seeds:
            return []

        id_gap = max(0, settings.search_seed_dedupe_message_gap)
        time_gap_ms = max(0, settings.search_seed_dedupe_time_gap_seconds) * 1000

        sorted_seeds = sorted(
            seeds,
            key=lambda seed: (
                seed.score,
                seed.message_date_ms or 0,
            ),
            reverse=True,
        )
        selected: List[SeedHit] = []

        for seed in sorted_seeds:
            too_close = False
            for existing in selected:
                if id_gap and abs(seed.message_id - existing.message_id) <= id_gap:
                    too_close = True
                    break
                if (
                    time_gap_ms
                    and seed.message_date_ms is not None
                    and existing.message_date_ms is not None
                    and abs(seed.message_date_ms - existing.message_date_ms)
                    <= time_gap_ms
                ):
                    too_close = True
                    break

            if too_close:
                continue

            selected.append(seed)

        if selected:
            return selected

        # Fallback: ensure at least one seed survives if dedupe removed all
        return sorted_seeds[:1]

    async def _build_candidate(self, seed: SeedHit) -> Optional[SearchResult]:
        neighbors = await self._fetch_neighbors(seed)
        if not neighbors:
            return None
        candidate = self._assemble_candidate(seed, neighbors)
        return candidate

    async def _fetch_neighbors(self, seed: SeedHit) -> List[MessageRecord]:
        window = max(0, settings.search_neighbor_message_window)
        min_id = max(seed.message_id - window, 0)
        max_id = seed.message_id + window
        message_clause = f"(message_id >= {min_id} AND message_id <= {max_id})"

        filters = [f"chat_id contains '{self._escape_chat_id(seed.chat_id)}'"]

        thread_id = self._coerce_int(seed.fields.get("thread_id"))
        if thread_id is not None:
            filters.append(f"thread_id = {thread_id}")

        time_clause = None
        if seed.message_date_ms is not None:
            window_ms = max(0, settings.search_neighbor_time_window_minutes) * 60_000
            start_ms = max(seed.message_date_ms - window_ms, 0)
            end_ms = seed.message_date_ms + window_ms
            time_clause = f"(message_date >= {start_ms} AND message_date <= {end_ms})"

        primary_clauses = filters + [message_clause]
        if time_clause:
            primary_clauses.append(time_clause)

        where_clause = " and ".join(primary_clauses) if primary_clauses else "true"
        yql = f"select * from message where {where_clause} order by message_id asc"

        body = {
            "yql": yql,
            "hits": settings.search_candidate_max_messages,
            "ranking": "default",
            "timeout": "5s",
        }

        data = await self._execute_search(body)
        messages = self._parse_message_hits(data.get("root", {}).get("children", []))

        if len(messages) < settings.search_neighbor_min_messages and time_clause:
            union_clause = " and ".join(
                filters + [f"({message_clause}) OR {time_clause}"]
            )
            union_yql = (
                f"select * from message where {union_clause} order by message_id asc"
            )
            union_body = {
                "yql": union_yql,
                "hits": settings.search_candidate_max_messages,
                "ranking": "default",
                "timeout": "5s",
            }
            union_data = await self._execute_search(union_body)
            extra = self._parse_message_hits(
                union_data.get("root", {}).get("children", [])
            )
            messages = self._merge_messages(messages, extra)

        messages.sort(key=lambda m: (m.message_id, m.message_date_ms or 0))
        return messages

    def _parse_message_hits(
        self, hits: Optional[Sequence[Dict[str, Any]]]
    ) -> List[MessageRecord]:
        if not hits:
            return []

        records: List[MessageRecord] = []
        for hit in hits:
            fields = hit.get("fields", {}) or {}
            message_id = self._coerce_int(fields.get("message_id"))
            if message_id is None:
                continue
            text = self._safe_text(fields.get("text"))
            message_date_ms = self._coerce_epoch_ms(fields.get("message_date"))
            records.append(
                MessageRecord(
                    message_id=message_id,
                    message_date_ms=message_date_ms,
                    sender=self._safe_optional_str(fields.get("sender")),
                    sender_username=self._safe_optional_str(
                        fields.get("sender_username")
                    ),
                    text=text,
                    source_title=self._safe_optional_str(fields.get("source_title")),
                    chat_type=self._safe_optional_str(fields.get("chat_type")),
                    chat_username=self._safe_optional_str(fields.get("chat_username")),
                    edit_date=self._coerce_epoch_seconds(fields.get("edit_date")),
                    thread_id=self._coerce_int(fields.get("thread_id")),
                    has_link=self._coerce_optional_bool(fields.get("has_link")),
                    raw_fields=fields,
                )
            )

        return records

    def _merge_messages(
        self, base: Sequence[MessageRecord], extra: Sequence[MessageRecord]
    ) -> List[MessageRecord]:
        merged: Dict[int, MessageRecord] = {msg.message_id: msg for msg in base}
        for msg in extra:
            existing = merged.get(msg.message_id)
            if existing is None or (not existing.text and msg.text):
                merged[msg.message_id] = msg
        result = list(merged.values())
        result.sort(key=lambda m: (m.message_id, m.message_date_ms or 0))
        return result

    def _assemble_candidate(
        self,
        seed: SeedHit,
        messages: Sequence[MessageRecord],
    ) -> Optional[SearchResult]:
        if not messages:
            return None

        dedup: Dict[int, MessageRecord] = {}
        for msg in messages:
            existing = dedup.get(msg.message_id)
            if existing is None or (not existing.text and msg.text):
                dedup[msg.message_id] = msg

        if seed.message_id not in dedup:
            dedup[seed.message_id] = MessageRecord(
                message_id=seed.message_id,
                message_date_ms=seed.message_date_ms,
                sender=self._safe_optional_str(seed.fields.get("sender")),
                sender_username=self._safe_optional_str(
                    seed.fields.get("sender_username")
                ),
                text=self._safe_text(seed.fields.get("text") or seed.text),
                source_title=self._safe_optional_str(seed.fields.get("source_title")),
                chat_type=self._safe_optional_str(seed.fields.get("chat_type")),
                chat_username=self._safe_optional_str(seed.fields.get("chat_username")),
                edit_date=self._coerce_epoch_seconds(seed.fields.get("edit_date")),
                thread_id=self._coerce_int(seed.fields.get("thread_id")),
                has_link=self._coerce_optional_bool(seed.fields.get("has_link")),
                raw_fields=seed.fields,
            )

        ordered = sorted(
            dedup.values(), key=lambda m: (m.message_id, m.message_date_ms or 0)
        )
        filtered = [msg for msg in ordered if msg.text]

        if not filtered:
            return None

        max_messages = max(1, settings.search_candidate_max_messages)
        if len(filtered) > max_messages:
            seed_index = next(
                (
                    idx
                    for idx, msg in enumerate(filtered)
                    if msg.message_id == seed.message_id
                ),
                len(filtered) // 2,
            )
            half = max_messages // 2
            start = max(0, seed_index - half)
            end = start + max_messages
            filtered = filtered[start:end]

        lines = [self._format_message_line(msg) for msg in filtered]
        max_chars = max(1, settings.search_candidate_token_limit) * 4
        text_block = "\n".join(lines)

        while len(text_block) > max_chars and len(filtered) > 1:
            drop_index = 0
            if filtered[0].message_id == seed.message_id and len(filtered) > 1:
                drop_index = 1
            filtered.pop(drop_index)
            lines.pop(drop_index)
            text_block = "\n".join(lines)

        if not text_block.strip():
            return None

        span_start = filtered[0]
        span_end = filtered[-1]
        span = SearchSpan(
            start_id=span_start.message_id,
            end_id=span_end.message_id,
            start_ts=span_start.message_date_ms,
            end_ts=span_end.message_date_ms,
        )

        seed_sender = self._safe_optional_str(seed.fields.get("sender"))
        seed_sender_username = self._safe_optional_str(
            seed.fields.get("sender_username")
        )
        seed_message_date_seconds = self._coerce_epoch_seconds(
            seed.fields.get("message_date")
        )
        source_title = self._safe_optional_str(seed.fields.get("source_title"))
        chat_type = self._safe_optional_str(seed.fields.get("chat_type"))
        chat_username = self._safe_optional_str(seed.fields.get("chat_username"))
        edit_date = self._coerce_epoch_seconds(seed.fields.get("edit_date"))
        thread_id = self._coerce_int(seed.fields.get("thread_id"))

        if not source_title:
            source_title = next(
                (msg.source_title for msg in filtered if msg.source_title), None
            )
        if not chat_type:
            chat_type = next((msg.chat_type for msg in filtered if msg.chat_type), None)
        if not chat_username:
            chat_username = next(
                (msg.chat_username for msg in filtered if msg.chat_username), None
            )
        if edit_date is None:
            edit_date = next(
                (msg.edit_date for msg in filtered if msg.edit_date is not None), None
            )
        if thread_id is None:
            thread_id = next(
                (msg.thread_id for msg in filtered if msg.thread_id is not None), None
            )
        if seed_sender is None:
            seed_sender = next((msg.sender for msg in filtered if msg.sender), None)
        if seed_sender_username is None:
            seed_sender_username = next(
                (msg.sender_username for msg in filtered if msg.sender_username),
                None,
            )

        link_values = [
            value for value in (msg.has_link for msg in filtered) if value is not None
        ]
        has_link_value = any(link_values) if link_values else None

        result = SearchResult(
            id=f"{seed.chat_id}:{span.start_id}-{span.end_id}",
            text=text_block,
            chat_id=seed.chat_id,
            message_id=seed.message_id,
            score=seed.score,
            seed_score=seed.score,
            retrieval_score=seed.score,
            rerank_score=None,
            span=span,
            message_count=len(filtered),
            sender=seed_sender,
            sender_username=seed_sender_username,
            chat_username=chat_username,
            message_date=seed_message_date_seconds,
            source_title=source_title,
            chat_type=chat_type,
            edit_date=edit_date,
            thread_id=thread_id,
            has_link=has_link_value,
        )
        return result

    def _format_message_line(self, msg: MessageRecord) -> str:
        text = msg.text.strip()
        if not text:
            return ""

        return text

    @staticmethod
    def _normalise_whitespace(value: str) -> str:
        return " ".join(value.split())

    def _prepare_bm25_query(self, query: str) -> tuple[str, Optional[str]]:
        """Normalise query for BM25 and compute language hints."""

        cleaned = self._normalise_whitespace(query)
        if not cleaned:
            return "", None

        tokens = self._TOKEN_RE.findall(cleaned.lower())
        if not tokens:
            return cleaned, None

        uses_cyrillic = any(self._CYRILLIC_RE.search(token) for token in tokens)
        language_hint = "uk" if uses_cyrillic else None
        return cleaned, language_hint

    def _safe_text(self, value: Any) -> str:
        if value is None:
            return ""
        text = str(value)
        return self._normalise_whitespace(text)

    @staticmethod
    def _safe_optional_str(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _coerce_optional_bool(value: Any) -> Optional[bool]:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        if text in {"true", "1", "yes"}:
            return True
        if text in {"false", "0", "no"}:
            return False
        return None

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _coerce_epoch_ms(cls, value: Any) -> Optional[int]:
        raw = cls._coerce_int(value)
        if raw is None:
            return None
        if raw < 10_000_000_000:  # seconds
            raw *= 1000
        return raw

    @classmethod
    def _coerce_epoch_seconds(cls, value: Any) -> Optional[int]:
        ms = cls._coerce_epoch_ms(value)
        if ms is None:
            return None
        return ms // 1000

    @staticmethod
    def _escape_chat_id(chat_id: str) -> str:
        return chat_id.replace("'", "%27")

    async def get_available_chats(self) -> List[ChatInfo]:
        """Get list of available chats with aggregation"""
        # First get chat counts
        query = {
            "yql": "select chat_id from message where true | all(group(chat_id) each(output(count())))",
            "hits": 0,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(f"{self.endpoint}/search/", json=query)
            response.raise_for_status()

        result = response.json()

        chats = []
        # Parse aggregation results and get chat IDs
        chat_data = {}
        if "root" in result and "children" in result["root"]:
            for group_list in result["root"]["children"]:
                if group_list.get("id") == "group:root:0" and "children" in group_list:
                    for chat_list in group_list["children"]:
                        if (
                            chat_list.get("label") == "chat_id"
                            and "children" in chat_list
                        ):
                            for chat_group in chat_list["children"]:
                                chat_id = chat_group["value"]
                                count = chat_group["fields"]["count()"]
                                chat_data[chat_id] = count

        # Now get a sample message from each chat to get source_title
        for chat_id, count in chat_data.items():
            title_query = {
                "yql": f"select source_title from message where chat_id = '{chat_id}'",
                "hits": 1,
            }

            async with httpx.AsyncClient() as client:
                title_response = await client.post(
                    f"{self.endpoint}/search/", json=title_query
                )
                title_response.raise_for_status()

            title_result = title_response.json()

            # Extract source_title from first hit
            title = f"Chat {chat_id}"  # fallback
            if (
                "root" in title_result
                and "children" in title_result["root"]
                and len(title_result["root"]["children"]) > 0
            ):
                first_hit = title_result["root"]["children"][0]
                if "fields" in first_hit and "source_title" in first_hit["fields"]:
                    source_title = first_hit["fields"]["source_title"]
                    if source_title and source_title.strip():
                        title = source_title

            chats.append(
                ChatInfo(chat_id=chat_id, source_title=title, message_count=count)
            )

        return chats

    async def _build_query(
        self, req: SearchRequest
    ) -> tuple[str, Dict[str, Any], Dict[str, str]]:
        """Build YQL, body, and query params for a search request (side-effect: may embed)."""
        yql_parts = ["select * from sources * where"]
        filters = []
        if req.chat_id:
            # Escape single quotes for YQL
            safe_chat_id = req.chat_id.replace("'", "%27")
            filters.append(f"chat_id contains '{safe_chat_id}'")
        if req.thread_id is not None:
            filters.append(f"thread_id = {req.thread_id}")

        vector_clause = None
        embedded_vector: Optional[List[float]] = None
        query_params: Dict[str, str] = {}

        # Determine vector field and ranking profile based on embedding model
        if settings.embed_model == "text-embedding-3-small":
            vector_field = "vector_small"
            ranking_profile = "hybrid-small"
            tensor_param = "qv_small"
            expected_dims = 1536
        else:  # text-embedding-3-large or other large models
            vector_field = "vector_large"
            ranking_profile = "hybrid-large"
            tensor_param = "qv_large"
            expected_dims = 3072

        if req.hybrid:
            try:
                embedded_vector = await self.embedder.embed(req.q)
                # Validate vector dimensions
                if len(embedded_vector) != expected_dims:
                    logger.warning(
                        f"Vector dimension mismatch: got {len(embedded_vector)}, expected {expected_dims} for {settings.embed_model}"
                    )
                vector_clause = f"([{{targetHits:{req.limit}}}]nearestNeighbor({vector_field},{tensor_param}))"
            except Exception as e:
                logger.warning(
                    f"Vector embedding failed, falling back to BM25 only: {e}"
                )
                req.hybrid = False

        bm25_query, language_hint = self._prepare_bm25_query(req.q)

        bm25_clause = f"(userInput(@q))"
        where_segments = []

        # Enable vector clause for hybrid search
        if vector_clause and req.hybrid and embedded_vector is not None:
            where_segments.append(vector_clause)

        where_segments.append(bm25_clause)
        core_clause = " or ".join(where_segments)
        if filters:
            core_clause = f"({core_clause}) and (" + " and ".join(filters) + ")"
        yql_parts.append(core_clause)
        yql = " ".join(yql_parts)

        body: Dict[str, Any] = {
            "yql": yql,
            "hits": req.limit,
            "ranking": ranking_profile if req.hybrid else "default",
            "timeout": "5s",
            "q": bm25_query,
        }

        # Add tensor in the correct format for Vespa
        if req.hybrid and embedded_vector is not None:
            body[f"input.query({tensor_param})"] = embedded_vector

        if language_hint:
            body["input.language"] = language_hint
            query_params["language"] = language_hint

        return yql, body, query_params


# Singleton search client for API module
vespa_search_client: Optional[VespaSearchClient] = None


async def get_search_client() -> VespaSearchClient:
    global vespa_search_client
    if vespa_search_client is None:
        vespa_search_client = VespaSearchClient()
    return vespa_search_client
