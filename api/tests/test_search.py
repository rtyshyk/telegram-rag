import pytest
from unittest.mock import AsyncMock, Mock, patch
from fastapi.testclient import TestClient

from api.app.main import app
from api.app.auth import create_session
from api.app.search import (
    get_search_client,
    SearchRequest,
    VespaSearchClient,
    SearchResult,
)
from api.app.settings import settings


def auth_cookie() -> dict[str, str]:
    token = create_session("tester")
    return {"rag_session": token}


def test_search_unauthorized():
    client = TestClient(app)
    resp = client.post("/search", json={"q": "hello"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_search_stub(monkeypatch):
    client = TestClient(app)
    search_client = await get_search_client()

    async def fake_search(req: SearchRequest):  # type: ignore
        return []

    search_client.search = fake_search  # type: ignore
    resp = client.post("/search", cookies=auth_cookie(), json={"q": "test"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["results"] == []


class TestVespaSearchClient:
    """Comprehensive tests for VespaSearchClient."""

    @pytest.fixture
    def mock_http_client(self):
        return AsyncMock()

    @pytest.fixture
    def mock_embedder(self):
        embedder = AsyncMock()
        embedder.embed.return_value = [0.1] * 1536  # Default to small model dimensions
        return embedder

    @pytest.fixture
    def search_client(self, mock_http_client, mock_embedder):
        client = VespaSearchClient(http=mock_http_client)
        client.embedder = mock_embedder
        return client

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_results(self, search_client):
        """Test that empty or whitespace-only queries return empty results."""
        req = SearchRequest(q="")
        results = await search_client.search(req)
        assert results == []

        req = SearchRequest(q="   ")
        results = await search_client.search(req)
        assert results == []

    @pytest.mark.asyncio
    async def test_hybrid_search_with_small_model(
        self, search_client, mock_http_client, mock_embedder
    ):
        """Test hybrid search with text-embedding-3-small model."""
        # Setup mock responses
        mock_embedder.embed.return_value = [0.1] * 1536
        mock_response = Mock()
        mock_response.json.return_value = {
            "root": {
                "children": [
                    {
                        "fields": {
                            "id": "test_id",
                            "text": "test text",
                            "chat_id": "test_chat",
                            "message_id": 123,
                            "chunk_idx": 0,
                        },
                        "relevance": 0.95,
                    }
                ]
            }
        }
        mock_http_client.post.return_value = mock_response

        with patch.object(settings, "embed_model", "text-embedding-3-small"):
            req = SearchRequest(q="test query", hybrid=True, limit=5)
            results = await search_client.search(req)

        # Verify embedding was called
        mock_embedder.embed.assert_called_once_with("test query")

        # Verify HTTP request was made with correct parameters
        mock_http_client.post.assert_called_once()
        call_args = mock_http_client.post.call_args

        # Check URL
        assert call_args[0][0].endswith("/search/")

        # Check request body
        body = call_args[1]["json"]
        assert "test query" in body["q"]
        assert body["hits"] == 5
        assert body["ranking"] == "hybrid-small"
        assert "vector_small" in body["yql"]
        assert "qv_small" in body["yql"]
        assert "input.query(qv_small)" in body
        assert len(body["input.query(qv_small)"]) == 1536

        # Verify results
        assert len(results) == 1
        assert results[0].id == "test_id"
        assert results[0].score == 0.95

    @pytest.mark.asyncio
    async def test_hybrid_search_with_large_model(
        self, search_client, mock_http_client, mock_embedder
    ):
        """Test hybrid search with text-embedding-3-large model."""
        # Setup mock responses
        mock_embedder.embed.return_value = [0.1] * 3072
        mock_response = Mock()
        mock_response.json.return_value = {"root": {"children": []}}
        mock_http_client.post.return_value = mock_response

        with patch.object(settings, "embed_model", "text-embedding-3-large"):
            req = SearchRequest(q="test query", hybrid=True)
            await search_client.search(req)

        # Verify HTTP request was made with correct parameters for large model
        call_args = mock_http_client.post.call_args
        body = call_args[1]["json"]

        assert body["ranking"] == "hybrid-large"
        assert "vector_large" in body["yql"]
        assert "qv_large" in body["yql"]
        assert "input.query(qv_large)" in body
        assert len(body["input.query(qv_large)"]) == 3072

    @pytest.mark.asyncio
    async def test_bm25_only_search(
        self, search_client, mock_http_client, mock_embedder
    ):
        """Test BM25-only search (hybrid=False)."""
        mock_response = Mock()
        mock_response.json.return_value = {"root": {"children": []}}
        mock_http_client.post.return_value = mock_response

        req = SearchRequest(q="test query", hybrid=False)
        await search_client.search(req)

        # Verify embedding was NOT called
        mock_embedder.embed.assert_not_called()

        # Verify HTTP request was made with correct parameters
        call_args = mock_http_client.post.call_args
        body = call_args[1]["json"]

        assert body["ranking"] == "default"
        assert "vector_small" not in body["yql"]
        assert "vector_large" not in body["yql"]
        assert "nearestNeighbor" not in body["yql"]
        assert "userInput(@q)" in body["yql"]
        assert "input.query(qv_small)" not in body
        assert "input.query(qv_large)" not in body

    @pytest.mark.asyncio
    async def test_search_with_chat_id_filter(
        self, search_client, mock_http_client, mock_embedder
    ):
        """Test search with chat_id filter."""
        mock_response = Mock()
        mock_response.json.return_value = {"root": {"children": []}}
        mock_http_client.post.return_value = mock_response

        req = SearchRequest(q="test query", chat_id="test_chat_123", hybrid=False)
        await search_client.search(req)

        # Verify YQL contains chat_id filter
        call_args = mock_http_client.post.call_args
        body = call_args[1]["json"]
        yql = body["yql"]

        assert "chat_id contains 'test_chat_123'" in yql
        assert "and" in yql  # Filter should be AND-ed with main query

    @pytest.mark.asyncio
    async def test_search_with_thread_id_filter(
        self, search_client, mock_http_client, mock_embedder
    ):
        """Test search with thread_id filter."""
        mock_response = Mock()
        mock_response.json.return_value = {"root": {"children": []}}
        mock_http_client.post.return_value = mock_response

        req = SearchRequest(q="test query", thread_id=456, hybrid=False)
        await search_client.search(req)

        # Verify YQL contains thread_id filter
        call_args = mock_http_client.post.call_args
        body = call_args[1]["json"]
        yql = body["yql"]

        assert "thread_id = 456" in yql
        assert "and" in yql  # Filter should be AND-ed with main query

    @pytest.mark.asyncio
    async def test_search_with_multiple_filters(
        self, search_client, mock_http_client, mock_embedder
    ):
        """Test search with both chat_id and thread_id filters."""
        mock_response = Mock()
        mock_response.json.return_value = {"root": {"children": []}}
        mock_http_client.post.return_value = mock_response

        req = SearchRequest(
            q="test query", chat_id="test_chat", thread_id=789, hybrid=False
        )
        await search_client.search(req)

        # Verify YQL contains both filters
        call_args = mock_http_client.post.call_args
        body = call_args[1]["json"]
        yql = body["yql"]

        assert "chat_id contains 'test_chat'" in yql
        assert "thread_id = 789" in yql
        assert yql.count("and") >= 2  # Should have multiple AND clauses

    @pytest.mark.asyncio
    async def test_chat_id_escaping(
        self, search_client, mock_http_client, mock_embedder
    ):
        """Test that single quotes in chat_id are properly escaped."""
        mock_response = Mock()
        mock_response.json.return_value = {"root": {"children": []}}
        mock_http_client.post.return_value = mock_response

        req = SearchRequest(q="test", chat_id="chat'with'quotes", hybrid=False)
        await search_client.search(req)

        # Verify single quotes are escaped
        call_args = mock_http_client.post.call_args
        body = call_args[1]["json"]
        yql = body["yql"]

        assert "chat%27with%27quotes" in yql

    @pytest.mark.asyncio
    async def test_embedding_failure_fallback(
        self, search_client, mock_http_client, mock_embedder
    ):
        """Test that embedding failures fall back to BM25-only search."""
        # Setup embedding to fail
        mock_embedder.embed.side_effect = Exception("Embedding service down")

        mock_response = Mock()
        mock_response.json.return_value = {"root": {"children": []}}
        mock_http_client.post.return_value = mock_response

        req = SearchRequest(q="test query", hybrid=True)
        await search_client.search(req)

        # Verify HTTP request was made with BM25-only parameters
        call_args = mock_http_client.post.call_args
        body = call_args[1]["json"]

        assert body["ranking"] == "default"  # Should fall back to default ranking
        assert "nearestNeighbor" not in body["yql"]
        assert "input.query(qv_small)" not in body
        assert "input.query(qv_large)" not in body

    @pytest.mark.asyncio
    async def test_vector_dimension_mismatch_warning(
        self, search_client, mock_http_client, mock_embedder
    ):
        """Test warning when vector dimensions don't match expected model dimensions."""
        # Setup wrong dimension vector
        mock_embedder.embed.return_value = [0.1] * 512  # Wrong dimensions

        mock_response = Mock()
        mock_response.json.return_value = {"root": {"children": []}}
        mock_http_client.post.return_value = mock_response

        with patch.object(settings, "embed_model", "text-embedding-3-small"):
            req = SearchRequest(q="test query", hybrid=True)

            # This should log a warning but still proceed
            with patch("api.app.search.logger") as mock_logger:
                await search_client.search(req)

                # Verify warning was logged
                mock_logger.warning.assert_called_once()
                warning_msg = mock_logger.warning.call_args[0][0]
                assert "Vector dimension mismatch" in warning_msg
                assert "got 512, expected 1536" in warning_msg

    @pytest.mark.asyncio
    async def test_vespa_error_handling(
        self, search_client, mock_http_client, mock_embedder
    ):
        """Test handling of Vespa HTTP errors."""
        # Setup HTTP client to raise an exception
        mock_http_client.post.side_effect = Exception("Vespa connection failed")

        req = SearchRequest(q="test query", hybrid=False)
        results = await search_client.search(req)

        # Should return empty results on error
        assert results == []

    @pytest.mark.asyncio
    async def test_search_result_parsing(
        self, search_client, mock_http_client, mock_embedder
    ):
        """Test comprehensive parsing of search results with all fields."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "root": {
                "children": [
                    {
                        "fields": {
                            "id": "chat123:msg456:chunk0",
                            "text": "This is a test message",
                            "chat_id": "test_chat",
                            "message_id": 456,
                            "chunk_idx": 0,
                            "sender": "John Doe",
                            "sender_username": "@johndoe",
                            "message_date": 1692825600,
                            "source_title": "Test Group",
                            "chat_type": "group",
                            "edit_date": 1692825700,
                            "thread_id": 789,
                            "has_link": True,
                        },
                        "relevance": 0.85,
                    },
                    {
                        "fields": {
                            "id": "chat456:msg789:chunk1",
                            "text": "Another message",
                            "chat_id": "test_chat_2",
                            "message_id": 789,
                            "chunk_idx": 1,
                            # Some fields missing to test defaults
                        },
                        "relevance": 0.72,
                    },
                ]
            }
        }
        mock_http_client.post.return_value = mock_response

        req = SearchRequest(q="test query", hybrid=False)
        results = await search_client.search(req)

        # Verify all fields are parsed correctly
        assert len(results) == 2

        # First result with all fields
        r1 = results[0]
        assert r1.id == "chat123:msg456:chunk0"
        assert r1.text == "This is a test message"
        assert r1.chat_id == "test_chat"
        assert r1.message_id == 456
        assert r1.chunk_idx == 0
        assert r1.score == 0.85
        assert r1.sender == "John Doe"
        assert r1.sender_username == "@johndoe"
        assert r1.message_date == 1692825600
        assert r1.source_title == "Test Group"
        assert r1.chat_type == "group"
        assert r1.edit_date == 1692825700
        assert r1.thread_id == 789
        assert r1.has_link is True

        # Second result with missing optional fields
        r2 = results[1]
        assert r2.id == "chat456:msg789:chunk1"
        assert r2.text == "Another message"
        assert r2.score == 0.72
        assert r2.sender is None
        assert r2.message_date is None

    @pytest.mark.asyncio
    async def test_custom_limit_parameter(
        self, search_client, mock_http_client, mock_embedder
    ):
        """Test that custom limit parameter is properly passed to Vespa."""
        mock_response = Mock()
        mock_response.json.return_value = {"root": {"children": []}}
        mock_http_client.post.return_value = mock_response

        req = SearchRequest(q="test query", limit=25, hybrid=False)
        await search_client.search(req)

        # Verify limit is set in request body
        call_args = mock_http_client.post.call_args
        body = call_args[1]["json"]

        assert body["hits"] == 25

        # For hybrid search, limit should also be in targetHits
        req = SearchRequest(q="test query", limit=25, hybrid=True)
        await search_client.search(req)

        call_args = mock_http_client.post.call_args
        body = call_args[1]["json"]
        yql = body["yql"]

        assert "targetHits:25" in yql
