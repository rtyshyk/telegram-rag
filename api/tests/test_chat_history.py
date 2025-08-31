"""Tests for chat history, cost estimator, and streaming chunk models."""

import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(BASE))

from app.chat import (
    ChatRequest,
    ChatMessage,
    ChatCostEstimator,
    ChatStreamChunk,
    ChatUsage,
)


def test_chat_models():
    """Test chat message and request validation including history."""
    msg = ChatMessage(role="user", content="Hello")
    assert msg.role == "user"
    assert msg.content == "Hello"

    history = [
        ChatMessage(role="user", content="What is the database?"),
        ChatMessage(role="assistant", content="I'll help you find that."),
    ]

    request = ChatRequest(q="Is SSL required?", k=5, model_id="gpt-5", history=history)
    assert request.q == "Is SSL required?"
    assert len(request.history) == 2
    assert request.history[0].role == "user"
    assert request.history[1].role == "assistant"


def test_cost_estimator():
    """Test cost estimation across several models."""
    estimator = ChatCostEstimator()
    test_cases = [
        ("gpt-5", 1000, 500),
        ("gpt-5-mini", 2000, 800),
        ("gpt-4o", 1500, 600),
    ]
    for model, prompt_tokens, completion_tokens in test_cases:
        cost = estimator.estimate_cost(model, prompt_tokens, completion_tokens)
        assert cost > 0


def test_chat_stream_chunk_models():
    """Test ChatStreamChunk variations and JSON serialization."""
    search_chunk = ChatStreamChunk(
        type="search",
        content="Searching...",
        search_results_count=5,
    )
    usage_chunk = ChatStreamChunk(
        type="end",
        usage=ChatUsage(
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
            cost_usd=0.05,
        ),
        timing_seconds=2.5,
    )
    reformulate_chunk = ChatStreamChunk(
        type="reformulate",
        content="Enhanced query",
        reformulated_query="What are the SSL requirements for database connections?",
    )

    search_json = search_chunk.model_dump_json()
    usage_json = usage_chunk.model_dump_json()
    reformulate_json = reformulate_chunk.model_dump_json()

    assert "search" in search_json
    assert "timing_seconds" in usage_json
    assert "reformulated_query" in reformulate_json
