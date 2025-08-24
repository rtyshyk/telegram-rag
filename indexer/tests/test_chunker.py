"""Tests for text chunker."""

import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path

# Add the indexer directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock settings globally before any imports
sys.modules["settings"] = MagicMock()
mock_settings = MagicMock()
mock_settings.target_chunk_tokens = 512
mock_settings.chunk_overlap_tokens = 50
sys.modules["settings"].settings = mock_settings

# Now we can safely import chunker
from chunker import TextChunker


class TestTextChunker:
    """Test TextChunker class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.chunker = TextChunker()

    def test_token_counting(self):
        """Test token counting functionality."""
        text = "This is a test"
        tokens = self.chunker.count_tokens(text)
        assert isinstance(tokens, int)
        assert tokens > 0

    def test_chunk_short_text(self):
        """Test chunking text shorter than target."""
        short_text = "This is a short text."

        with patch.object(self.chunker, "count_tokens", return_value=10):
            chunks = self.chunker.chunk_text(short_text)

        assert len(chunks) == 1
        # chunk_text returns (full_text, bm25_text) tuples
        assert chunks[0] == (short_text, short_text)

    def test_chunk_with_header(self):
        """Test chunking with header."""
        text = "This is test content."
        header = "Header: Test"

        with patch.object(self.chunker, "count_tokens", return_value=10):
            chunks = self.chunker.chunk_text(text, header)

        assert len(chunks) == 1
        full_text, bm25_text = chunks[0]
        assert header in full_text
        assert bm25_text == text

    def test_empty_text_handling(self):
        """Test handling of empty or whitespace-only text."""
        assert self.chunker.chunk_text("") == []
        assert self.chunker.chunk_text("   ") == []
        assert self.chunker.chunk_text("\n\t  \n") == []

    def test_single_sentence_handling(self):
        """Test handling of single sentence text."""
        sentence = "This is a single sentence."

        with patch.object(self.chunker, "count_tokens", return_value=5):
            chunks = self.chunker.chunk_text(sentence)

        assert len(chunks) == 1
        full_text, bm25_text = chunks[0]
        assert full_text == sentence
        assert bm25_text == sentence
