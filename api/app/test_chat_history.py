"""Test file to verify chat history functionality."""

import json
from pydantic import ValidationError


def test_chat_models():
    """Test chat model validation."""
    from api.app.chat import ChatRequest, ChatMessage
    
    # Test ChatMessage model
    msg = ChatMessage(role="user", content="Hello")
    assert msg.role == "user"
    assert msg.content == "Hello"
    
    # Test ChatRequest with history
    history = [
        ChatMessage(role="user", content="What is the database?"),
        ChatMessage(role="assistant", content="I'll help you find that."),
    ]
    
    request = ChatRequest(
        q="Is SSL required?",
        k=5,
        model_id="gpt-5",
        history=history
    )
    
    assert request.q == "Is SSL required?"
    assert len(request.history) == 2
    assert request.history[0].role == "user"
    assert request.history[1].role == "assistant"
    
    print("✅ Chat models validation passed")
    return True


def test_cost_estimator():
    """Test the cost estimation functionality."""
    from api.app.chat import ChatCostEstimator
    
    estimator = ChatCostEstimator()
    
    # Test cost estimation for different models
    test_cases = [
        ("gpt-5", 1000, 500),
        ("gpt-5-mini", 2000, 800),
        ("gpt-4o", 1500, 600),
    ]
    
    for model, prompt_tokens, completion_tokens in test_cases:
        cost = estimator.estimate_cost(model, prompt_tokens, completion_tokens)
        print(f"{model}: {prompt_tokens} + {completion_tokens} tokens = ${cost:.6f}")
        assert cost > 0  # Cost should be positive
    
    print("✅ Cost estimator test passed")
    return True


def test_chat_stream_chunk():
    """Test ChatStreamChunk model."""
    from api.app.chat import ChatStreamChunk, ChatUsage
    
    # Test different chunk types
    search_chunk = ChatStreamChunk(
        type="search",
        content="Searching...",
        search_results_count=5
    )
    
    usage_chunk = ChatStreamChunk(
        type="end",
        usage=ChatUsage(
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
            cost_usd=0.05
        ),
        timing_seconds=2.5
    )
    
    reformulate_chunk = ChatStreamChunk(
        type="reformulate",
        content="Enhanced query",
        reformulated_query="What are the SSL requirements for database connections?"
    )
    
    # Verify JSON serialization works
    search_json = search_chunk.model_dump_json()
    usage_json = usage_chunk.model_dump_json()
    reformulate_json = reformulate_chunk.model_dump_json()
    
    assert "search" in search_json
    assert "timing_seconds" in usage_json
    assert "reformulated_query" in reformulate_json
    
    print("✅ ChatStreamChunk model test passed")
    return True


if __name__ == "__main__":
    print("Testing chat history functionality...")
    
    try:
        test_chat_models()
    except Exception as e:
        print(f"❌ Chat models test failed: {e}")
    
    try:
        test_cost_estimator()
    except Exception as e:
        print(f"❌ Cost estimator test failed: {e}")
    
    try:
        test_chat_stream_chunk()
    except Exception as e:
        print(f"❌ ChatStreamChunk test failed: {e}")
    
    print("All tests completed!")
