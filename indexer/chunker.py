"""Text chunking utilities."""

import logging
import tiktoken
from typing import List, Tuple
from settings import settings

logger = logging.getLogger(__name__)


class TextChunker:
    """Handles text chunking with overlap and token awareness."""

    def __init__(self, model_name: str = "gpt-3.5-turbo"):
        self.encoder = tiktoken.encoding_for_model(model_name)
        self.target_tokens = settings.target_chunk_tokens
        self.overlap_tokens = settings.chunk_overlap_tokens

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self.encoder.encode(text))

    def chunk_text(self, text: str, header: str = "") -> List[Tuple[str, str]]:
        """
        Chunk text into overlapping segments.

        Args:
            text: Text to chunk
            header: Header to prepend to each chunk

        Returns:
            List of (full_text, bm25_text) tuples
        """
        if not text.strip():
            return []

        # If text is short enough, return as single chunk
        total_tokens = self.count_tokens(header + "\n\n" + text)
        if total_tokens <= self.target_tokens:
            full_text = f"{header}\n\n{text}" if header else text
            return [(full_text, text)]

        # Split into chunks
        chunks = []
        text_tokens = self.encoder.encode(text)
        header_tokens = self.encoder.encode(header + "\n\n") if header else []
        available_tokens = self.target_tokens - len(header_tokens)

        start = 0
        chunk_idx = 0

        while start < len(text_tokens):
            # Calculate end position
            end = min(start + available_tokens, len(text_tokens))

            # Extract chunk tokens
            chunk_tokens = text_tokens[start:end]
            chunk_text = self.encoder.decode(chunk_tokens)

            # Clean up chunk boundaries (avoid splitting words/sentences)
            if end < len(text_tokens):
                chunk_text = self._clean_chunk_boundary(chunk_text)

            # Create full text with header
            if header:
                full_text = f"{header}\n\n{chunk_text}"
            else:
                full_text = chunk_text

            chunks.append((full_text, chunk_text))

            # Move start position with overlap
            if end >= len(text_tokens):
                break

            start = max(start + available_tokens - self.overlap_tokens, start + 1)
            chunk_idx += 1

        return chunks

    def _clean_chunk_boundary(self, text: str) -> str:
        """Clean chunk boundary to avoid splitting mid-word or mid-sentence."""
        # Try to end at sentence boundary
        for delimiter in [". ", "! ", "? ", "\n\n"]:
            if delimiter in text:
                pos = text.rfind(delimiter)
                if pos > len(text) * 0.8:  # Only if we don't lose too much
                    return text[: pos + len(delimiter)]

        # Try to end at word boundary
        if " " in text:
            pos = text.rfind(" ")
            if pos > len(text) * 0.9:  # Only if we don't lose much
                return text[:pos]

        # Avoid splitting URLs or code blocks
        if "```" in text:
            pos = text.rfind("```")
            if pos > len(text) * 0.7:
                return text[:pos]

        return text
