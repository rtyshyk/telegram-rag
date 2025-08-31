"""Chat endpoint with RAG capabilities using OpenAI."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

import tiktoken
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from .search import SearchRequest, SearchResult, get_search_client
from .models import resolve_model_id, DEFAULT_MODEL_ID
from .settings import settings

logger = logging.getLogger(__name__)


class ChatMessage(BaseModel):
    """A single message in the conversation history."""

    role: str = Field(..., description="Role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")


class ChatFilters(BaseModel):
    """Filters for chat search - same as SearchRequest but optional."""

    chat_ids: Optional[List[str]] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    thread_id: Optional[int] = None


class ChatRequest(BaseModel):
    model_config = {"protected_namespaces": ()}

    q: str = Field(..., min_length=1, description="Query text")
    k: int = Field(default=12, ge=1, le=30, description="Number of search results")
    model_id: Optional[str] = Field(default=None, description="Model ID from /models")
    filters: Optional[ChatFilters] = Field(default=None, description="Search filters")
    use_current_filters: bool = Field(default=True, description="Use current filters")
    history: Optional[List[ChatMessage]] = Field(
        default=None, description="Conversation history"
    )


class ChatCitation(BaseModel):
    id: str
    chat_id: str
    message_id: int
    chunk_idx: int
    source_title: Optional[str] = None
    message_date: Optional[int] = None


class ChatUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: Optional[float] = None


class ChatStreamChunk(BaseModel):
    """Streaming chunk for chat response."""

    type: str = Field(
        ...,
        description="Type of chunk: 'search', 'reformulate', 'start', 'content', 'citations', 'usage', 'end'",
    )
    content: Optional[str] = Field(
        default=None, description="Content for content chunks"
    )
    citations: Optional[List[ChatCitation]] = Field(
        default=None, description="Citations data"
    )
    usage: Optional[ChatUsage] = Field(default=None, description="Usage information")
    timing_seconds: Optional[float] = Field(
        default=None, description="Timing information in seconds"
    )
    search_results_count: Optional[int] = Field(
        default=None, description="Number of search results"
    )
    reformulated_query: Optional[str] = Field(
        default=None, description="Reformulated query based on history"
    )


class ChatRateLimiter:
    """Simple in-memory rate limiter for chat requests."""

    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: Dict[str, List[float]] = {}

    def is_allowed(self, user_id: str) -> tuple[bool, Optional[float]]:
        """Check if request is allowed. Returns (allowed, retry_after_seconds)."""
        now = time.time()
        user_requests = self.requests.get(user_id, [])

        # Clean old requests outside the window
        cutoff = now - self.window_seconds
        user_requests = [req_time for req_time in user_requests if req_time > cutoff]

        if len(user_requests) >= self.max_requests:
            # Find when the oldest request will expire
            oldest_request = min(user_requests)
            retry_after = oldest_request + self.window_seconds - now
            return False, max(0, retry_after)

        # Record this request
        user_requests.append(now)
        self.requests[user_id] = user_requests
        return True, None


# Global rate limiter
chat_rate_limiter = ChatRateLimiter(
    max_requests=settings.chat_rate_limit_rpm, window_seconds=60
)


class ContextAssembler:
    """Assembles search results into a context window within token budget."""

    def __init__(self, model: str = DEFAULT_MODEL_ID):
        try:
            self.tokenizer = tiktoken.encoding_for_model(model)
        except KeyError:
            # Fallback to cl100k_base for unknown models
            self.tokenizer = tiktoken.get_encoding("cl100k_base")

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self.tokenizer.encode(text))

    def assemble_context(
        self,
        results: List[SearchResult],
    ) -> tuple[str, List[int]]:
        """
        Assemble context from search results (no token budget enforced).
        Returns (context_text, selected_indices).
        """
        if not results:
            return "", []

        # Use results as-is from Vespa (already ranked with recency if configured)
        sorted_results = [(i, result) for i, result in enumerate(results)]

        # Deduplicate by (chat_id, message_id) - keep highest scoring chunk
        seen_messages = {}
        deduplicated = []

        for orig_idx, result in sorted_results:
            key = (result.chat_id, result.message_id)
            if key not in seen_messages:
                seen_messages[key] = (orig_idx, result)
                deduplicated.append((orig_idx, result))

        # Include all deduplicated chunks (caller is responsible for any upstream limits).
        context_parts: List[str] = []
        selected_indices: List[int] = []
        for orig_idx, result in deduplicated:
            header = self._format_chunk_header(result, len(selected_indices) + 1)
            chunk_text = f"{header}\n{result.text}\n"
            context_parts.append(chunk_text)
            selected_indices.append(orig_idx)

        # Assemble final context
        context = "\n".join(context_parts)
        return context, selected_indices

    def _format_chunk_header(self, result: SearchResult, citation_num: int) -> str:
        """Format a header for a context chunk."""
        chat_title = result.source_title or f"Chat {result.chat_id}"
        date_str = "Unknown date"

        if result.message_date:
            dt = datetime.fromtimestamp(result.message_date)
            date_str = dt.strftime("%Y-%m-%d %H:%M")

        return (
            f"[{citation_num}] {chat_title} — {date_str} — message {result.message_id}:"
        )


class ChatCostEstimator:
    """Estimates costs for chat completions."""

    def __init__(self):
        # OpenAI GPT-5 pricing (per 1M tokens) - actual pricing
        self.completion_prices = {
            # GPT-5 models - actual pricing from OpenAI
            "gpt-5": {"input": 1.25, "output": 10.00},
            "gpt-5-mini": {"input": 0.25, "output": 2.00},
            "gpt-5-nano": {"input": 0.05, "output": 0.40},
        }

    def estimate_cost(
        self, model: str, prompt_tokens: int, completion_tokens: int
    ) -> float:
        """Estimate cost for a completion."""
        if model not in self.completion_prices:
            # Default to gpt-5 pricing for unknown models
            model = "gpt-5"

        prices = self.completion_prices[model]
        input_cost = (prompt_tokens / 1_000_000) * prices["input"]
        output_cost = (completion_tokens / 1_000_000) * prices["output"]
        return input_cost + output_cost


class QueryReformulator:
    """Reformulates queries based on conversation history."""

    def __init__(self, openai_client: AsyncOpenAI):
        self.openai_client = openai_client
        # Load reformulation prompt from external file. Fail fast if missing/unreadable.
        prompt_path = Path(__file__).parent / "prompts" / "reformulation_prompt.txt"
        if not prompt_path.exists():
            raise FileNotFoundError(
                f"Reformulation prompt file not found: {prompt_path}. Create the file or disable reformulation."
            )
        try:
            self.reformulation_prompt = prompt_path.read_text().strip()
            if not self.reformulation_prompt:
                raise ValueError("Reformulation prompt file is empty")
        except Exception as e:
            raise RuntimeError(f"Failed to load reformulation prompt: {e}") from e

    async def reformulate_query(
        self, question: str, history: List[ChatMessage], model: str
    ) -> str:
        """Reformulate a query based on conversation history."""
        if not history or len(history) == 0:
            return question

        # Format history for the prompt
        history_text = []
        for msg in history[-6:]:  # Use last 6 messages for context
            role = "User" if msg.role == "user" else "Assistant"
            history_text.append(f"{role}: {msg.content}")

        if not history_text:
            return question

        history_str = "\n".join(history_text)

        try:
            response = await self.openai_client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": self.reformulation_prompt.format(
                            history=history_str, question=question
                        ),
                    }
                ],
            )

            reformulated = response.choices[0].message.content.strip()
            # Fallback to original if reformulation failed
            return reformulated if reformulated else question

        except Exception as e:
            logger.warning(f"Query reformulation failed: {e}")
            return question


class ChatService:
    """Service for handling chat requests with OpenAI."""

    def __init__(self):
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for chat")

        self.openai_client = AsyncOpenAI(
            api_key=settings.openai_api_key,
        )

        # Load system prompt
        self.system_prompt = self._load_system_prompt()

        # Initialize cost estimator and query reformulator
        self.cost_estimator = ChatCostEstimator()
        self.query_reformulator = QueryReformulator(self.openai_client)

    def _load_system_prompt(self) -> str:
        """Load system prompt from file."""
        prompt_path = Path(__file__).parent / "prompts" / "system_chat.txt"
        if not prompt_path.exists():
            raise FileNotFoundError(
                f"System prompt file not found at {prompt_path}. Ensure prompts/system_chat.txt exists."
            )
        try:
            content = prompt_path.read_text().strip()
        except Exception as e:
            raise RuntimeError(
                f"Failed reading system prompt file {prompt_path}: {e}"
            ) from e
        if not content:
            raise ValueError(f"System prompt file {prompt_path} is empty")
        return content

    def _resolve_model_id(self, model_id: Optional[str]) -> str:
        """Resolve model ID, using default if not provided."""
        return model_id or DEFAULT_MODEL_ID

    async def chat_stream(
        self, request: ChatRequest, user_id: str
    ) -> AsyncGenerator[str, None]:
        """Process a chat request with streaming response."""
        start_time = time.time()

        # Rate limiting
        allowed, retry_after = chat_rate_limiter.is_allowed(user_id)
        if not allowed:
            error_chunk = ChatStreamChunk(
                type="error",
                content=f"Rate limit exceeded. Retry after {int(retry_after or 0)} seconds.",
            )
            yield f"data: {error_chunk.model_dump_json()}\n\n"
            return

        try:
            model_id = self._resolve_model_id(request.model_id)

            # Query reformulation phase
            reformulated_query = request.q
            if request.history and len(request.history) > 0:
                yield f"data: {ChatStreamChunk(type='reformulate', content='Analyzing conversation context...').model_dump_json()}\n\n"

                reformulated_query = await self.query_reformulator.reformulate_query(
                    request.q, request.history, model_id
                )

                if reformulated_query != request.q:
                    reformulate_chunk = ChatStreamChunk(
                        type="reformulate",
                        content=f"Enhanced query based on conversation",
                        reformulated_query=reformulated_query,
                    )
                    yield f"data: {reformulate_chunk.model_dump_json()}\n\n"

            # Search phase
            yield f"data: {ChatStreamChunk(type='search', content='Searching your Telegram data...').model_dump_json()}\n\n"

            search_client = await get_search_client()
            search_request = self._build_search_request(request, reformulated_query)
            search_results = await search_client.search(search_request)

            search_chunk = ChatStreamChunk(
                type="search",
                content=f"Found {len(search_results)} relevant messages",
                search_results_count=len(search_results),
            )
            yield f"data: {search_chunk.model_dump_json()}\n\n"

            if not search_results:
                # No context found
                no_data_chunk = ChatStreamChunk(
                    type="content",
                    content="I don't see this information in your Telegram data.",
                )
                yield f"data: {no_data_chunk.model_dump_json()}\n\n"

                end_chunk = ChatStreamChunk(
                    type="end",
                    citations=[],
                    usage=ChatUsage(
                        prompt_tokens=0,
                        completion_tokens=0,
                        total_tokens=0,
                        cost_usd=0.0,
                    ),
                    timing_seconds=round(time.time() - start_time, 2),
                )
                yield f"data: {end_chunk.model_dump_json()}\n\n"
                return

            # Assemble context
            assembler = ContextAssembler(model_id)
            context, selected_indices = assembler.assemble_context(search_results)

            # Prepare messages with history
            current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            system_message = self.system_prompt.format(
                current_datetime=current_datetime
            )

            messages = [{"role": "system", "content": system_message}]

            # Add conversation history (limit to recent messages to stay within token budget)
            if request.history:
                # Take the last few exchanges to stay within budget
                history_to_include = request.history[
                    -16:
                ]  # Last 8 exchanges (16 messages)
                for msg in history_to_include:
                    messages.append({"role": msg.role, "content": msg.content})

            # Add current question with context
            messages.append(
                {
                    "role": "user",
                    "content": f"CONTEXT:\n{context}\n\nQUESTION: {reformulated_query}",
                }
            )

            # Signal start of generation
            yield f"data: {ChatStreamChunk(type='start', content='Generating response...').model_dump_json()}\n\n"

            # Initialize variables that will be used later
            usage_data = None  # Will hold usage from API if provided (some models don't send it in stream)
            content_received = False
            full_response_content = (
                ""  # Accumulate streamed content for manual token counting fallback
            )

            # Call OpenAI with streaming
            logger.info(f"Calling OpenAI with model: {model_id}")
            logger.info(f"Message count: {len(messages)}")
            logger.info(f"Last message preview: {messages[-1]['content'][:200]}...")

            stream = await self.openai_client.chat.completions.create(
                model=model_id, messages=messages, stream=True
            )

            # Stream the response
            async for chunk in stream:
                logger.debug(f"Received chunk: {chunk}")

                if chunk.choices and chunk.choices[0].delta.content:
                    content_received = True
                    content_text = chunk.choices[0].delta.content
                    full_response_content += content_text

                    content_chunk = ChatStreamChunk(
                        type="content", content=content_text
                    )
                    logger.debug(f"Streaming content: {content_text}")
                    yield f"data: {content_chunk.model_dump_json()}\n\n"

                # Capture usage data if available
                if hasattr(chunk, "usage") and chunk.usage:
                    cost = self.cost_estimator.estimate_cost(
                        model_id,
                        chunk.usage.prompt_tokens,
                        chunk.usage.completion_tokens,
                    )
                    usage_data = ChatUsage(
                        prompt_tokens=chunk.usage.prompt_tokens,
                        completion_tokens=chunk.usage.completion_tokens,
                        total_tokens=chunk.usage.total_tokens,
                        cost_usd=round(cost, 6),
                    )

            logger.info(f"Content received: {content_received}")

            # Fallback manual usage estimation if streaming API didn't return usage
            if usage_data is None:
                try:
                    # Tokenizer (reuse assembler tokenizer if available, else new one)
                    try:
                        tokenizer = tiktoken.encoding_for_model(model_id)
                    except KeyError:
                        tokenizer = tiktoken.get_encoding("cl100k_base")

                    # Build same messages list again to estimate prompt tokens
                    # NOTE: This is an approximation; OpenAI applies per-message/role overhead.
                    # We'll approximate overhead as 4 tokens per message + 2 final (as per older ChatML guidelines).
                    prompt_tokens_raw = 0
                    message_overhead = 4
                    system_message = self.system_prompt.format(
                        current_datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    )
                    prompt_messages: List[dict[str, str]] = [
                        {"role": "system", "content": system_message}
                    ]
                    if request.history:
                        history_to_include = request.history[-8:]
                        for msg in history_to_include:
                            prompt_messages.append(
                                {"role": msg.role, "content": msg.content}
                            )
                    # Recreate context (approx) for counting – safe reassembly
                    assembler_for_count = ContextAssembler(model_id)
                    context_for_count, _ = assembler_for_count.assemble_context(
                        []
                    )  # empty context for simplicity
                    # Use earlier built context variable where available (if defined in outer scope)
                    try:
                        # context variable defined earlier in function scope
                        existing_context = context  # type: ignore  # noqa
                    except NameError:
                        existing_context = ""
                    prompt_messages.append(
                        {
                            "role": "user",
                            "content": f"CONTEXT:\n{existing_context}\n\nQUESTION: {reformulated_query}",
                        }
                    )
                    for m in prompt_messages:
                        prompt_tokens_raw += (
                            len(tokenizer.encode(m["content"])) + message_overhead
                        )
                    prompt_tokens = prompt_tokens_raw + 2  # final priming
                    completion_tokens = (
                        len(tokenizer.encode(full_response_content))
                        if content_received
                        else 0
                    )
                    total_tokens = prompt_tokens + completion_tokens
                    cost = self.cost_estimator.estimate_cost(
                        model_id, prompt_tokens, completion_tokens
                    )
                    usage_data = ChatUsage(
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        cost_usd=round(cost, 6),
                    )
                    logger.debug(
                        "Manual usage fallback applied: prompt=%s completion=%s total=%s cost=%s",
                        prompt_tokens,
                        completion_tokens,
                        total_tokens,
                        usage_data.cost_usd,
                    )
                except Exception as e:
                    logger.warning(f"Manual usage estimation failed: {e}")

            # Build citations
            citations = []
            for i, orig_idx in enumerate(selected_indices):
                result = search_results[orig_idx]
                citations.append(
                    ChatCitation(
                        id=result.id,
                        chat_id=result.chat_id,
                        message_id=result.message_id,
                        chunk_idx=result.chunk_idx,
                        source_title=result.source_title,
                        message_date=result.message_date,
                    )
                )

            # Send citations
            citations_chunk = ChatStreamChunk(type="citations", citations=citations)
            yield f"data: {citations_chunk.model_dump_json()}\n\n"

            # Send final metadata
            timing_seconds = round(time.time() - start_time, 2)

            end_chunk = ChatStreamChunk(
                type="end",
                usage=usage_data
                or ChatUsage(
                    prompt_tokens=0, completion_tokens=0, total_tokens=0, cost_usd=0.0
                ),
                timing_seconds=timing_seconds,
            )
            yield f"data: {end_chunk.model_dump_json()}\n\n"

        except Exception as e:
            logger.error(f"OpenAI API error in streaming: {e}")
            error_chunk = ChatStreamChunk(type="error", content=f"Error: {str(e)}")
            yield f"data: {error_chunk.model_dump_json()}\n\n"

    def _build_search_request(
        self, chat_request: ChatRequest, query: str = None
    ) -> SearchRequest:
        """Convert ChatRequest to SearchRequest."""
        search_req = SearchRequest(
            q=query or chat_request.q,
            limit=chat_request.k,
            hybrid=True,  # Always use hybrid search for chat
        )

        if chat_request.filters:
            # Map ChatFilters to SearchRequest fields
            # Note: SearchRequest currently only supports single chat_id and thread_id
            # This is a simplification - in a full implementation, we'd extend SearchRequest
            if chat_request.filters.chat_ids and len(chat_request.filters.chat_ids) > 0:
                search_req.chat_id = chat_request.filters.chat_ids[
                    0
                ]  # Use first chat_id

            if chat_request.filters.thread_id is not None:
                search_req.thread_id = chat_request.filters.thread_id

        return search_req


# Global chat service instance
chat_service: Optional[ChatService] = None


async def get_chat_service() -> ChatService:
    """Get or create chat service instance."""
    global chat_service
    if chat_service is None:
        chat_service = ChatService()
    return chat_service
