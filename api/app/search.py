"""Search utilities: perform hybrid (vector+bm25) search against Vespa."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel

from .settings import settings

logger = logging.getLogger(__name__)


class SearchRequest(BaseModel):
    q: str
    limit: int = settings.search_default_limit
    chat_id: Optional[str] = None
    thread_id: Optional[int] = None
    hybrid: bool = True


class SearchResult(BaseModel):
    id: str
    text: str
    chat_id: str
    message_id: int
    chunk_idx: int
    score: float
    retrieval_score: Optional[float] = None
    rerank_score: Optional[float] = None
    sender: Optional[str] = None
    sender_username: Optional[str] = None
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


class CohereReranker:
    """Optional reranker using Cohere's Rerank API (or local stub)."""

    _RERANK_ENDPOINT = "https://api.cohere.com/v1/rerank"

    def __init__(self, http: Optional[httpx.AsyncClient] = None):
        self.stub = bool(settings.cohere_stub)
        self.api_key = settings.cohere_api_key
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
                "Rerank enabled but no Cohere API key provided; falling back to Vespa ranking."
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
            logger.warning("Cohere client not available; skipping rerank.")
            return results[:top_n]

        payload = {
            "model": self.model,
            "query": query,
            "documents": [r.text for r in results],
            "top_n": min(top_n, len(results)),
            "return_documents": False,
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
            logger.warning("Cohere rerank failed: %s", exc)
            return results[:top_n]

        reranked: List[SearchResult] = []
        seen_indices: set[int] = set()

        for item in data.get("results", []):
            idx = item.get("index")
            if idx is None or idx >= len(results):
                continue
            seen_indices.add(idx)
            result = results[idx]
            score = float(item.get("relevance_score", result.score))
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
    def __init__(self, http: Optional[httpx.AsyncClient] = None):
        self.endpoint = settings.vespa_endpoint.rstrip("/")
        self.http = http or httpx.AsyncClient(timeout=20)
        self.embedder = EmbeddingProvider()
        self.reranker: Optional[CohereReranker] = None

        if settings.rerank_enabled:
            reranker = CohereReranker()
            if reranker.enabled:
                self.reranker = reranker

    async def close(self):
        await self.http.aclose()
        if self.reranker:
            await self.reranker.aclose()

    async def search(self, req: SearchRequest) -> List[SearchResult]:
        if not req.q.strip():
            return []
        candidate_limit = req.limit
        reranker = self.reranker
        if reranker and reranker.enabled:
            candidate_limit = max(req.limit, settings.rerank_candidate_limit)
        fetch_request = (
            req
            if candidate_limit == req.limit
            else req.model_copy(update={"limit": candidate_limit})
        )
        yql, body, query_params = await self._build_query(fetch_request)
        try:
            resp = await self.http.post(f"{self.endpoint}/search/", json=body)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"Vespa search error: {e}")
            return []
        logger.debug(
            "YQL=%s hits_field=%s", yql, data.get("root", {}).get("fields", {})
        )
        hits = data.get("root", {}).get("children", []) or []
        results: List[SearchResult] = []
        for h in hits:
            fields = h.get("fields", {})
            base_score = float(h.get("relevance", 0.0))
            results.append(
                SearchResult(
                    id=fields.get("id", ""),
                    text=fields.get("text", ""),
                    chat_id=fields.get("chat_id", ""),
                    message_id=int(fields.get("message_id", 0) or 0),
                    chunk_idx=int(fields.get("chunk_idx", 0) or 0),
                    score=base_score,
                    retrieval_score=base_score,
                    sender=fields.get("sender"),
                    sender_username=fields.get("sender_username"),
                    message_date=fields.get("message_date"),
                    source_title=fields.get("source_title"),
                    chat_type=fields.get("chat_type"),
                    edit_date=fields.get("edit_date"),
                    thread_id=fields.get("thread_id"),
                    has_link=fields.get("has_link"),
                )
            )
        if reranker and reranker.enabled:
            return await reranker.rerank(req.q, results, req.limit)
        return results[: req.limit]

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
            "q": req.q,
        }

        # Add tensor in the correct format for Vespa
        if req.hybrid and embedded_vector is not None:
            body[f"input.query({tensor_param})"] = embedded_vector

        return yql, body, query_params


# Singleton search client for API module
vespa_search_client: Optional[VespaSearchClient] = None


async def get_search_client() -> VespaSearchClient:
    global vespa_search_client
    if vespa_search_client is None:
        vespa_search_client = VespaSearchClient()
    return vespa_search_client
