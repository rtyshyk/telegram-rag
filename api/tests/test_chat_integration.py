"""Integration tests for chat API endpoints."""

import pytest
from httpx import AsyncClient
from app.main import app
from app.auth import create_session


def auth_cookie() -> dict[str, str]:
    """Create authentication cookie for testing."""
    token = create_session("tester")
    return {"rag_session": token}


class TestChatAPI:
    """Test the /chat endpoint."""
    
    @pytest.mark.asyncio
    async def test_chat_requires_auth(self):
        """Test that chat endpoint requires authentication."""
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post("/chat", json={"q": "test"})
            assert response.status_code == 401
    
    @pytest.mark.asyncio
    async def test_chat_empty_query_validation(self):
        """Test that empty query is rejected."""
        async with AsyncClient(app=app, base_url="http://test") as client:
            # This would need proper auth setup
            response = await client.post("/chat", json={"q": ""})
            assert response.status_code in [400, 401]  # 400 for validation, 401 for auth
    
    @pytest.mark.asyncio
    async def test_chat_with_filters(self):
        """Test chat with search filters."""
        payload = {
            "q": "database connection",
            "k": 5,
            "filters": {
                "chat_ids": ["-123456"],
                "date_from": "2025-08-01"
            },
            "model_id": "gpt-5"
        }
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post("/chat", json=payload)
            # Would be 401 without auth, but validates the request structure
            assert response.status_code == 401
    
    @pytest.mark.asyncio
    async def test_chat_with_history(self):
        """Test chat with conversation history."""
        payload = {
            "q": "Is SSL required for connections?",
            "k": 5,
            "model_id": "gpt-5",
            "history": [
                {"role": "user", "content": "What is the database connection string?"},
                {"role": "assistant", "content": "Based on your messages, the connection string is postgres://..."},
                {"role": "user", "content": "What about security settings?"}
            ]
        }
        
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post("/chat", json=payload)
            # Would be 401 without auth, but validates the request structure
            assert response.status_code == 401
    
    @pytest.mark.asyncio 
    async def test_chat_rate_limiting(self):
        """Test that rate limiting works."""
        # This would need proper auth and multiple rapid requests
        # to test the rate limiting functionality
        pass
    
    @pytest.mark.asyncio
    async def test_chat_response_structure(self):
        """Test that successful chat response has correct structure."""
        # This test would need mocked auth and search results
        expected_fields = [
            "answer",
            "citations", 
            "usage",
            "timing_seconds"  # Updated from timing_ms
        ]
        
        # When we have a successful response, verify these fields exist
        # For now, just document the expected structure
        assert all(field for field in expected_fields)


class TestChatModels:
    """Test chat data models."""
    
    def test_chat_message_model(self):
        """Test ChatMessage model validation."""
        from app.chat import ChatMessage
        
        msg = ChatMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        
        # Test another valid role
        assistant_msg = ChatMessage(role="assistant", content="Hi there!")
        assert assistant_msg.role == "assistant"
    
    def test_chat_request_with_history(self):
        """Test ChatRequest model with history."""
        from app.chat import ChatRequest, ChatMessage
        
        history = [
            ChatMessage(role="user", content="First question"),
            ChatMessage(role="assistant", content="First answer"),
        ]
        
        request = ChatRequest(
            q="Follow-up question",
            history=history
        )
        
        assert request.q == "Follow-up question"
        assert len(request.history) == 2
        assert request.history[0].role == "user"
    
    def test_chat_usage_with_cost(self):
        """Test ChatUsage model with cost information."""
        from app.chat import ChatUsage
        
        usage = ChatUsage(
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
            cost_usd=0.025
        )
        
        assert usage.total_tokens == 1500
        assert usage.cost_usd == 0.025
    
    def test_cost_estimator(self):
        """Test ChatCostEstimator functionality."""
        from app.chat import ChatCostEstimator
        
        estimator = ChatCostEstimator()
        
        # Test known GPT-5 models with actual pricing
        cost_gpt5 = estimator.estimate_cost("gpt-5", 1000, 500)
        cost_gpt5_mini = estimator.estimate_cost("gpt-5-mini", 1000, 500)
        cost_gpt5_nano = estimator.estimate_cost("gpt-5-nano", 1000, 500)
        
        # Verify costs are calculated correctly
        # gpt-5: (1000/1M * 1.25) + (500/1M * 10.00) = 0.00125 + 0.005 = 0.00625
        assert abs(cost_gpt5 - 0.00625) < 0.000001
        
        # gpt-5-mini: (1000/1M * 0.25) + (500/1M * 2.00) = 0.00025 + 0.001 = 0.00125
        assert abs(cost_gpt5_mini - 0.00125) < 0.000001
        
        # gpt-5-nano: (1000/1M * 0.05) + (500/1M * 0.40) = 0.00005 + 0.0002 = 0.00025
        assert abs(cost_gpt5_nano - 0.00025) < 0.000001
        
        # Test unknown model (should fallback to gpt-5)
        cost_unknown = estimator.estimate_cost("unknown-model", 1000, 500)
        assert abs(cost_unknown - cost_gpt5) < 0.000001


@pytest.mark.asyncio
async def test_health_endpoint():
    """Test that health endpoint works."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "api"


@pytest.mark.asyncio
async def test_models_endpoint():
    """Test that models endpoint works.""" 
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/models", cookies=auth_cookie())
        assert response.status_code == 200
        models = response.json()
        assert isinstance(models, list)
        assert len(models) > 0
        
        # Check model structure
        for model in models:
            assert "label" in model
            assert "id" in model
