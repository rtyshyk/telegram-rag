"""Vespa client for document feeding."""

import asyncio
import logging
from typing import List, Dict, Any, Optional
import json
import httpx
from models import VespaDocument, IndexerMetrics
from settings import settings

logger = logging.getLogger(__name__)


class VespaClient:
    """Client for feeding documents to Vespa."""

    def __init__(self):
        self.endpoint = settings.vespa_endpoint
        self.feed_url_base = f"{self.endpoint}/document/v1/default/message/docid"
        self.metrics = IndexerMetrics()

        # HTTP client with retries
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0), limits=httpx.Limits(max_connections=10)
        )

    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()

    async def feed_document(self, doc: VespaDocument) -> bool:
        """
        Feed a single document to Vespa.

        Args:
            doc: Document to feed

        Returns:
            True if successful, False otherwise
        """
        doc_url = f"{self.feed_url_base}/{doc.id}"

        # Prepare document for Vespa
        vespa_doc = {
            "fields": {
                "id": doc.id,
                "text": doc.text,
                "bm25_text": doc.bm25_text,
                "vector": doc.vector,
                "chat_id": doc.chat_id,
                "message_id": doc.message_id,
                "chunk_idx": doc.chunk_idx,
                "source_title": doc.source_title or "",
                "sender": doc.sender or "",
                "sender_username": doc.sender_username or "",
                "chat_type": doc.chat_type or "",
                "message_date": doc.message_date,
                "edit_date": doc.edit_date,
                "thread_id": doc.thread_id,
                "has_link": doc.has_link,
                "date": doc.message_date,  # For backward compatibility
            }
        }
        # Retry with exponential backoff
        for attempt in range(3):
            try:
                response = await self.client.post(
                    doc_url,
                    json=vespa_doc,
                    headers={"Content-Type": "application/json"},
                )

                if response.status_code in [200, 201]:
                    self.metrics.vespa_feed_success += 1
                    return True
                else:
                    logger.warning(
                        f"Vespa feed failed: {response.status_code} {response.text}"
                    )
            except Exception as e:
                base_ms = getattr(settings, "backoff_base_ms", 500)
                try:
                    base_ms = float(base_ms)
                except Exception:
                    base_ms = 500.0
                wait_time = (base_ms * (2**attempt)) / 1000
                logger.warning(f"Vespa feed error (attempt {attempt + 1}): {e}")

                if attempt < 2:
                    self.metrics.vespa_feed_retries += 1
                    await asyncio.sleep(wait_time)
                else:
                    self.metrics.vespa_feed_failures += 1
                    return False
            else:
                # Non-success response path
                if attempt < 2:
                    self.metrics.vespa_feed_retries += 1
                    base_ms = getattr(settings, "backoff_base_ms", 500)
                    try:
                        base_ms = float(base_ms)
                    except Exception:
                        base_ms = 500.0
                    wait_time = (base_ms * (2**attempt)) / 1000
                    await asyncio.sleep(wait_time)
                else:
                    self.metrics.vespa_feed_failures += 1
                    return False

        return False

    async def feed_documents(self, docs: List[VespaDocument]) -> int:
        """
        Feed multiple documents to Vespa with concurrency control.

        Args:
            docs: List of documents to feed

        Returns:
            Number of successfully fed documents
        """
        if not docs:
            return 0

        # Limit concurrency to avoid overwhelming Vespa
        semaphore = asyncio.Semaphore(5)

        async def feed_with_semaphore(doc: VespaDocument) -> bool:
            async with semaphore:
                return await self.feed_document(doc)

        # Feed all documents concurrently
        tasks = [feed_with_semaphore(doc) for doc in docs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Count successes
        success_count = sum(1 for result in results if result is True)
        logger.info(f"Fed {success_count}/{len(docs)} documents to Vespa")

        return success_count

    async def delete_document(self, doc_id: str) -> bool:
        """
        Delete a document from Vespa.

        Args:
            doc_id: Document ID to delete

        Returns:
            True if successful, False otherwise
        """
        doc_url = f"{self.feed_url_base}/{doc_id}"

        try:
            response = await self.client.delete(doc_url)

            if response.status_code in [200, 404]:  # 404 is OK - already deleted
                return True
            else:
                logger.warning(
                    f"Vespa delete failed: {response.status_code} {response.text}"
                )
                return False

        except Exception as e:
            logger.error(f"Vespa delete error: {e}")
            return False

    async def delete_message_chunks(self, chat_id: str, message_id: int) -> int:
        """
        Delete all chunks for a message.

        Args:
            chat_id: Chat ID
            message_id: Message ID

        Returns:
            Number of deleted chunks
        """
        # Since we don't know exactly how many chunks exist, we'll try a reasonable range
        deleted_count = 0

        for chunk_idx in range(10):  # Assume max 10 chunks per message
            doc_id = f"{chat_id}:{message_id}:{chunk_idx}:v{settings.chunking_version}"
            if await self.delete_document(doc_id):
                deleted_count += 1

        logger.info(f"Deleted {deleted_count} chunks for message {message_id}")
        return deleted_count

    async def health_check(self) -> bool:
        """Check if Vespa is healthy."""
        try:
            response = await self.client.get(
                f"{settings.vespa_endpoint.replace(':8080', ':19071')}/ApplicationStatus"
            )
            return response.status_code == 200
        except Exception:
            return False
