"""Tests for the search decision logic."""

import pytest
from unittest.mock import AsyncMock, Mock, patch

# Import from the correct module path
import sys
from pathlib import Path

# Add the api directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.chat import SearchDecisionMaker, ChatMessage, QueryReformulator
from app.settings import settings


class TestSearchDecisionMaker:
    """Test search decision logic."""

    @pytest.fixture
    def mock_openai_client(self):
        """Mock OpenAI client."""
        client = Mock()
        client.chat = Mock()
        client.chat.completions = Mock()
        client.chat.completions.create = AsyncMock()
        return client

    @pytest.fixture
    def search_decision_maker(self, mock_openai_client):
        """Create SearchDecisionMaker instance with mocked client."""
        with patch("app.chat.Path.exists", return_value=True), patch(
            "app.chat.Path.read_text",
            return_value="test prompt {chat_history} {question}",
        ):
            return SearchDecisionMaker(mock_openai_client)

    @pytest.mark.asyncio
    async def test_should_search_no_history(self, search_decision_maker):
        """Test that search is performed when no history exists."""
        result = await search_decision_maker.should_search("What is the weather?", [])
        assert result is True

    @pytest.mark.asyncio
    async def test_should_search_with_skip_decision(
        self, search_decision_maker, mock_openai_client
    ):
        """Test that search is skipped when AI decides to skip."""
        # Mock the OpenAI response to return SKIP_SEARCH
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message = Mock()
        mock_response.choices[0].message.content = "SKIP_SEARCH"
        mock_openai_client.chat.completions.create.return_value = mock_response

        history = [
            ChatMessage(role="user", content="What is 2+2?"),
            ChatMessage(role="assistant", content="2+2 equals 4"),
        ]

        result = await search_decision_maker.should_search("Thanks!", history)
        assert result is False

    @pytest.mark.asyncio
    async def test_should_search_with_yes_decision(
        self, search_decision_maker, mock_openai_client
    ):
        """Test that search is performed when AI decides to search."""
        # Mock the OpenAI response to return YES_SEARCH
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message = Mock()
        mock_response.choices[0].message.content = "YES_SEARCH"
        mock_openai_client.chat.completions.create.return_value = mock_response

        history = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there!"),
        ]

        result = await search_decision_maker.should_search(
            "Tell me about climate change", history
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_should_search_api_error_raises_exception(
        self, search_decision_maker, mock_openai_client
    ):
        """Test that search decision raises exception when API call fails."""
        mock_openai_client.chat.completions.create.side_effect = Exception("API Error")

        history = [ChatMessage(role="user", content="Hello")]

        with pytest.raises(RuntimeError, match="Failed to make search decision"):
            await search_decision_maker.should_search("What's the weather?", history)

    @pytest.mark.asyncio
    async def test_uses_correct_model_and_settings(
        self, search_decision_maker, mock_openai_client
    ):
        """Test that search decision uses correct model and settings."""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message = Mock()
        mock_response.choices[0].message.content = "YES_SEARCH"
        mock_openai_client.chat.completions.create.return_value = mock_response

        history = [ChatMessage(role="user", content="Hello")]

        await search_decision_maker.should_search("Test question", history)

        # Verify the call was made with correct parameters
        call_args = mock_openai_client.chat.completions.create.call_args
        assert call_args.kwargs["model"] == settings.chat_search_decision_model
        # No temperature parameter should be passed


class TestQueryReformulator:
    """Test query reformulation logic."""

    @pytest.fixture
    def mock_openai_client(self):
        """Mock OpenAI client."""
        client = Mock()
        client.chat = Mock()
        client.chat.completions = Mock()
        client.chat.completions.create = AsyncMock()
        return client

    @pytest.fixture
    def query_reformulator(self, mock_openai_client):
        """Create QueryReformulator instance with mocked client."""
        with patch("app.chat.Path.exists", return_value=True), patch(
            "app.chat.Path.read_text",
            return_value="test prompt {chat_history} {question}",
        ):
            return QueryReformulator(mock_openai_client)

    @pytest.mark.asyncio
    async def test_reformulate_query_no_history(self, query_reformulator):
        """Test that original query is returned when no history exists."""
        result = await query_reformulator.reformulate_query("What is the weather?", [])
        assert result == "What is the weather?"

    @pytest.mark.asyncio
    async def test_reformulate_query_with_history(
        self, query_reformulator, mock_openai_client
    ):
        """Test that query is reformulated when history exists."""
        # Mock the OpenAI response
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message = Mock()
        mock_response.choices[0].message.content = "weather conditions today"
        mock_openai_client.chat.completions.create.return_value = mock_response

        history = [
            ChatMessage(role="user", content="I need to go outside"),
            ChatMessage(role="assistant", content="That sounds good!"),
        ]

        result = await query_reformulator.reformulate_query("What's it like?", history)
        assert result == "weather conditions today"

    @pytest.mark.asyncio
    async def test_reformulate_query_api_error_raises_exception(
        self, query_reformulator, mock_openai_client
    ):
        """Test that reformulation raises exception when API call fails."""
        mock_openai_client.chat.completions.create.side_effect = Exception("API Error")

        history = [ChatMessage(role="user", content="Hello")]

        with pytest.raises(RuntimeError, match="Failed to reformulate query"):
            await query_reformulator.reformulate_query("What's the weather?", history)

    @pytest.mark.asyncio
    async def test_reformulate_query_empty_response_raises_exception(
        self, query_reformulator, mock_openai_client
    ):
        """Test that reformulation raises exception when API returns empty response."""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message = Mock()
        mock_response.choices[0].message.content = ""
        mock_openai_client.chat.completions.create.return_value = mock_response

        history = [ChatMessage(role="user", content="Hello")]

        with pytest.raises(RuntimeError, match="Failed to reformulate query"):
            await query_reformulator.reformulate_query("What's the weather?", history)

    @pytest.mark.asyncio
    async def test_uses_correct_model_and_settings(
        self, query_reformulator, mock_openai_client
    ):
        """Test that reformulation uses correct model and settings."""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message = Mock()
        mock_response.choices[0].message.content = "reformulated query"
        mock_openai_client.chat.completions.create.return_value = mock_response

        history = [ChatMessage(role="user", content="Hello")]

        await query_reformulator.reformulate_query("Test question", history)

        # Verify the call was made with correct parameters
        call_args = mock_openai_client.chat.completions.create.call_args
        assert call_args.kwargs["model"] == settings.chat_reformulation_model
        # No temperature parameter should be passed
