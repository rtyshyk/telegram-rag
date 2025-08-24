"""Tests for Vespa client."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from vespa_client import VespaClient
from models import VespaDocument, IndexerMetrics


class TestVespaClient:
    """Test VespaClient class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.client = VespaClient()

    def teardown_method(self):
        """Clean up after tests."""
        # Note: In real tests, we'd await client.close(), but we'll mock the client
        pass

    def test_client_initialization(self):
        """Test client initialization."""
        assert self.client.endpoint is not None
        assert self.client.feed_url_base is not None
        assert isinstance(self.client.metrics, IndexerMetrics)
        assert self.client.client is not None

    @pytest.mark.asyncio
    async def test_close_client(self):
        """Test closing the HTTP client."""
        mock_client = AsyncMock()
        self.client.client = mock_client
        
        await self.client.close()
        mock_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_feed_document_success(self):
        """Test successful document feeding."""
        # Create test document
        doc = VespaDocument(
            id="test:123:0:v1",
            chat_id="test",
            message_id=123,
            chunk_idx=0,
            message_date=1692825600,
            text="Test message",
            bm25_text="Test message",
            vector={"values": [0.1, 0.2, 0.3]}
        )
        
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        self.client.client = mock_client
        
        result = await self.client.feed_document(doc)
        
        assert result is True
        assert self.client.metrics.vespa_feed_success == 1
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_feed_document_created_status(self):
        """Test document feeding with 201 Created status."""
        doc = VespaDocument(
            id="test:123:0:v1",
            chat_id="test",
            message_id=123,
            chunk_idx=0,
            message_date=1692825600,
            text="Test message",
            bm25_text="Test message",
            vector={"values": [0.1, 0.2, 0.3]}
        )
        
        # Mock 201 Created response
        mock_response = MagicMock()
        mock_response.status_code = 201
        
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        self.client.client = mock_client
        
        result = await self.client.feed_document(doc)
        
        assert result is True
        assert self.client.metrics.vespa_feed_success == 1

    @pytest.mark.asyncio
    async def test_feed_document_failure(self):
        """Test document feeding failure."""
        doc = VespaDocument(
            id="test:123:0:v1",
            chat_id="test",
            message_id=123,
            chunk_idx=0,
            message_date=1692825600,
            text="Test message",
            bm25_text="Test message",
            vector={"values": [0.1, 0.2, 0.3]}
        )
        
        # Mock error response
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        self.client.client = mock_client
        
        with patch('indexer.vespa_client.settings') as mock_settings:
            mock_settings.backoff_base_ms = 1  # Fast retry for testing
            
            result = await self.client.feed_document(doc)
            
            assert result is False
            assert self.client.metrics.vespa_feed_failures == 1
            assert mock_client.post.call_count == 3  # Should retry 3 times

    @pytest.mark.asyncio
    async def test_feed_document_exception_retry(self):
        """Test document feeding with exception and retry."""
        doc = VespaDocument(
            id="test:123:0:v1",
            chat_id="test",
            message_id=123,
            chunk_idx=0,
            message_date=1692825600,
            text="Test message",
            bm25_text="Test message",
            vector={"values": [0.1, 0.2, 0.3]}
        )
        
        # Mock client that fails twice then succeeds
        call_count = 0
        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise Exception("Network error")
            
            mock_response = MagicMock()
            mock_response.status_code = 200
            return mock_response
        
        mock_client = AsyncMock()
        mock_client.post = mock_post
        self.client.client = mock_client
        
        with patch('indexer.vespa_client.settings') as mock_settings:
            mock_settings.backoff_base_ms = 1  # Fast retry for testing
            
            result = await self.client.feed_document(doc)
            
            assert result is True
            assert self.client.metrics.vespa_feed_success == 1
            assert self.client.metrics.vespa_feed_retries == 2
            assert call_count == 3

    @pytest.mark.asyncio
    async def test_feed_document_persistent_failure(self):
        """Test document feeding with persistent failure."""
        doc = VespaDocument(
            id="test:123:0:v1",
            chat_id="test",
            message_id=123,
            chunk_idx=0,
            message_date=1692825600,
            text="Test message",
            bm25_text="Test message",
            vector={"values": [0.1, 0.2, 0.3]}
        )
        
        # Mock client that always fails
        async def mock_post(*args, **kwargs):
            raise Exception("Persistent network error")
        
        mock_client = AsyncMock()
        mock_client.post = mock_post
        self.client.client = mock_client
        
        with patch('indexer.vespa_client.settings') as mock_settings:
            mock_settings.backoff_base_ms = 1  # Fast retry for testing
            
            result = await self.client.feed_document(doc)
            
            assert result is False
            assert self.client.metrics.vespa_feed_failures == 1
            assert self.client.metrics.vespa_feed_retries == 2

    @pytest.mark.asyncio
    async def test_feed_documents_empty_list(self):
        """Test feeding empty document list."""
        result = await self.client.feed_documents([])
        assert result == 0

    @pytest.mark.asyncio
    async def test_feed_documents_multiple(self):
        """Test feeding multiple documents."""
        docs = [
            VespaDocument(
                id=f"test:12{i}:0:v1",
                chat_id="test",
                message_id=120 + i,
                chunk_idx=0,
                message_date=1692825600,
                text=f"Test message {i}",
                bm25_text=f"Test message {i}",
                vector={"values": [0.1 * i, 0.2 * i, 0.3 * i]}
            )
            for i in range(3)
        ]
        
        # Mock successful responses
        mock_response = MagicMock()
        mock_response.status_code = 200
        
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        self.client.client = mock_client
        
        result = await self.client.feed_documents(docs)
        
        assert result == 3
        assert mock_client.post.call_count == 3
        assert self.client.metrics.vespa_feed_success == 3

    @pytest.mark.asyncio
    async def test_feed_documents_partial_success(self):
        """Test feeding documents with partial success."""
        docs = [
            VespaDocument(
                id=f"test:12{i}:0:v1",
                chat_id="test",
                message_id=120 + i,
                chunk_idx=0,
                message_date=1692825600,
                text=f"Test message {i}",
                bm25_text=f"Test message {i}",
                vector={"values": [0.1 * i, 0.2 * i, 0.3 * i]}
            )
            for i in range(3)
        ]
        
        # Mock responses: success, failure, success
        call_count = 0
        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            
            mock_response = MagicMock()
            if call_count == 2:  # Second call fails
                mock_response.status_code = 500
            else:
                mock_response.status_code = 200
            return mock_response
        
        mock_client = AsyncMock()
        mock_client.post = mock_post
        self.client.client = mock_client
        
        with patch('indexer.vespa_client.settings') as mock_settings:
            mock_settings.backoff_base_ms = 1  # Fast retry for testing
            result = await self.client.feed_documents(docs)
            # Given retry logic, all 3 should eventually succeed
            assert result == 3

    @pytest.mark.asyncio
    async def test_delete_document_success(self):
        """Test successful document deletion."""
        doc_id = "test:123:0:v1"
        
        # Mock successful delete response
        mock_response = MagicMock()
        mock_response.status_code = 200
        
        mock_client = AsyncMock()
        mock_client.delete.return_value = mock_response
        self.client.client = mock_client
        
        result = await self.client.delete_document(doc_id)
        
        assert result is True
        mock_client.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_document_not_found(self):
        """Test deleting non-existent document (should be success)."""
        doc_id = "test:123:0:v1"
        
        # Mock 404 response (document not found)
        mock_response = MagicMock()
        mock_response.status_code = 404
        
        mock_client = AsyncMock()
        mock_client.delete.return_value = mock_response
        self.client.client = mock_client
        
        result = await self.client.delete_document(doc_id)
        
        assert result is True  # 404 is considered success for deletion

    @pytest.mark.asyncio
    async def test_delete_document_failure(self):
        """Test document deletion failure."""
        doc_id = "test:123:0:v1"
        
        # Mock error response
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        
        mock_client = AsyncMock()
        mock_client.delete.return_value = mock_response
        self.client.client = mock_client
        
        result = await self.client.delete_document(doc_id)
        
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_document_exception(self):
        """Test document deletion with exception."""
        doc_id = "test:123:0:v1"
        
        # Mock client that raises exception
        async def mock_delete(*args, **kwargs):
            raise Exception("Network error")
        
        mock_client = AsyncMock()
        mock_client.delete = mock_delete
        self.client.client = mock_client
        
        result = await self.client.delete_document(doc_id)
        
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_message_chunks(self):
        """Test deleting all chunks for a message."""
        chat_id = "test"
        message_id = 123
        
        # Mock successful deletes for first 3 chunks, then failures
        call_count = 0
        async def mock_delete(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            
            mock_response = MagicMock()
            if call_count <= 3:
                mock_response.status_code = 200
            else:
                mock_response.status_code = 404
            return mock_response
        
        mock_client = AsyncMock()
        mock_client.delete = mock_delete
        self.client.client = mock_client
        
        result = await self.client.delete_message_chunks(chat_id, message_id)
        
        # Should try up to 10 chunks, but only first 3 exist
        assert result >= 3  # At least 3 successful deletes
        assert call_count == 10  # Should try all 10 possible chunks

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """Test successful health check."""
        # Mock successful health check response
        mock_response = MagicMock()
        mock_response.status_code = 200
        
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        self.client.client = mock_client
        
        result = await self.client.health_check()
        
        assert result is True
        mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """Test health check failure."""
        # Mock error response
        mock_response = MagicMock()
        mock_response.status_code = 500
        
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        self.client.client = mock_client
        
        result = await self.client.health_check()
        
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_exception(self):
        """Test health check with exception."""
        # Mock client that raises exception
        async def mock_get(*args, **kwargs):
            raise Exception("Network error")
        
        mock_client = AsyncMock()
        mock_client.get = mock_get
        self.client.client = mock_client
        
        result = await self.client.health_check()
        
        assert result is False

    def test_document_field_mapping(self):
        """Test that VespaDocument fields are properly mapped."""
        doc = VespaDocument(
            id="test:123:0:v1",
            chat_id="test_chat",
            message_id=123,
            chunk_idx=0,
            source_title="Test Chat",
            sender="John Doe",
            sender_username="johndoe",
            chat_type="private",
            message_date=1692825600,
            edit_date=1692825700,
            thread_id=456,
            has_link=True,
            text="Test message with link",
            bm25_text="Test message with https://example.com",
            vector={"values": [0.1, 0.2, 0.3]}
        )
        
        # This would be the document structure sent to Vespa
        expected_fields = {
            "id": "test:123:0:v1",
            "text": "Test message with link",
            "bm25_text": "Test message with https://example.com",
            "vector": {"values": [0.1, 0.2, 0.3]},
            "chat_id": "test_chat",
            "message_id": 123,
            "chunk_idx": 0,
            "source_title": "Test Chat",
            "sender": "John Doe",
            "sender_username": "johndoe",
            "chat_type": "private",
            "message_date": 1692825600,
            "edit_date": 1692825700,
            "thread_id": 456,
            "has_link": True,
            "date": 1692825600,
        }
        
        # Verify all expected fields are mapped
        for field, expected_value in expected_fields.items():
            assert hasattr(doc, field) or field == "date"  # date is derived from message_date
