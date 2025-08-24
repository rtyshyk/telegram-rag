"""Cost estimation utilities."""

import logging
from typing import Dict

logger = logging.getLogger(__name__)


class CostEstimator:
    """Estimates costs for various operations."""
    
    def __init__(self):
        # OpenAI pricing (per 1k tokens) - update as needed
        self.embedding_prices = {
            "text-embedding-3-large": 0.00013,
            "text-embedding-3-small": 0.00002,
            "text-embedding-ada-002": 0.0001,
        }
    
    def estimate_embedding_cost(self, texts: list, model: str) -> Dict[str, float]:
        """
        Estimate embedding cost for a list of texts.
        
        Args:
            texts: List of texts to embed
            model: Embedding model name
            
        Returns:
            Dict with token count and cost estimate
        """
        # Rough token estimation: ~0.75 tokens per word
        total_words = sum(len(text.split()) for text in texts)
        estimated_tokens = total_words * 0.75
        
        price_per_1k = self.embedding_prices.get(model, 0.0001)
        estimated_cost = (estimated_tokens / 1000) * price_per_1k
        
        return {
            "tokens": estimated_tokens,
            "cost_usd": estimated_cost,
            "model": model,
            "text_count": len(texts)
        }
    
    def format_cost_summary(self, total_tokens: int, total_cost: float, model: str) -> str:
        """Format a human-readable cost summary."""
        return (
            f"Embedding summary: {total_tokens:,} tokens, "
            f"${total_cost:.4f} estimated cost ({model})"
        )
