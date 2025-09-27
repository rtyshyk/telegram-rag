#!/usr/bin/env python3
"""
Telegram RAG Indexer - Phase 2 Implementation

Indexes Telegram messages with embedding and chunking.
"""

import asyncio
import argparse
import logging
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import hashlib

from settings import settings, CLIArgs
from db import DatabaseManager
from telethon_client import TelethonClientWrapper
from normalize import normalize_text, create_header, compose_message_with_reply
from chunker import TextChunker
from embedder import Embedder
from vespa_client import VespaClient
from cost import CostEstimator
from models import Chunk, VespaDocument, IndexerMetrics

logger = logging.getLogger(__name__)


class TelegramIndexer:
    """Main indexer class for processing Telegram messages."""

    def __init__(self, args: CLIArgs):
        self.args = args
        self.db = DatabaseManager(settings.database_url)
        self.tg_client = TelethonClientWrapper()
        self.chunker = TextChunker()
        self.embedder = Embedder(self.db)
        self.vespa_client = VespaClient()
        self.cost_estimator = CostEstimator()
        self.metrics = IndexerMetrics()

        # Apply CLI overrides
        if args.embed_batch_size:
            self.embedder.batch_size = args.embed_batch_size
        if args.embed_concurrency:
            self.embedder.concurrency = args.embed_concurrency

    async def initialize(self):
        """Initialize all clients and connections."""
        logger.info("Initializing indexer...")

        await self.db.initialize()
        await self.tg_client.start()

        # Check Vespa health
        if not await self.vespa_client.health_check():
            logger.warning("Vespa health check failed - documents may not be indexed")

        logger.info("Indexer initialized successfully")

    async def cleanup(self):
        """Clean up resources."""
        logger.info("Cleaning up...")

        await self.tg_client.stop()
        await self.vespa_client.close()
        await self.db.close()

    async def run_once(self) -> None:
        """Run one-shot indexing."""
        if self.args.days is None:
            logger.info("Starting one-shot indexing for full history")
        else:
            logger.info(f"Starting one-shot indexing for {self.args.days} days")

        # Get chat list - either from args or all available chats
        chat_list = self.args.get_chat_list()
        if not chat_list:
            logger.info("No specific chats provided, getting all available chats...")
            chat_list = await self.tg_client.get_all_chats()
            logger.info(f"Found {len(chat_list)} chats to process")

        logger.info(f"Target chats: {', '.join(chat_list)}")

        # Resolve chats
        resolved_chats = await self.tg_client.resolve_chats(chat_list)

        valid_chats = []
        for name, info in resolved_chats.items():
            if "error" in info:
                logger.error(f"Failed to resolve '{name}': {info['error']}")
            else:
                valid_chats.append((name, info))
                logger.info(f"✓ {name} -> {info['title']} ({info['type']})")

        if not valid_chats:
            raise ValueError("No valid chats found")

        # Calculate date range (None means full history)
        if self.args.days is None:
            since_date = None
            logger.info("Fetching messages for entire available history")
        else:
            since_date = datetime.now() - timedelta(days=self.args.days)
            logger.info(
                f"Fetching messages since {since_date.strftime('%Y-%m-%d %H:%M')}"
            )

        # Process each chat with global message limit
        total_messages_processed = 0
        for chat_name, chat_info in valid_chats:
            logger.info(f"Processing chat: {chat_info['title']}")

            # Calculate remaining message limit
            remaining_limit = None
            if self.args.limit_messages:
                remaining_limit = self.args.limit_messages - total_messages_processed
                if remaining_limit <= 0:
                    logger.info(
                        f"Message limit ({self.args.limit_messages}) reached, stopping"
                    )
                    break

            processed_count = await self.process_chat(
                chat_info, since_date, remaining_limit
            )
            total_messages_processed += processed_count

        # Print final metrics
        self.print_metrics()

    async def process_chat(
        self,
        chat_info: Dict[str, Any],
        since_date: datetime,
        limit_messages: Optional[int] = None,
    ) -> int:
        """Process all messages in a chat.

        Returns:
            Number of messages processed from this chat
        """
        chat_id = chat_info["id"]
        entity = chat_info["entity"]

        messages_processed = 0

        try:
            async for message in self.tg_client.get_messages(
                entity, limit=limit_messages, since_date=since_date
            ):
                self.metrics.messages_scanned += 1

                # Extract message data
                msg_data = self.tg_client.extract_message_data(message, entity)
                msg_data["chat_id"] = chat_id
                msg_data["source_title"] = chat_info["title"]
                msg_data["chat_username"] = chat_info.get("username")

                # Skip if no text content
                if not msg_data["text"].strip():
                    continue

                # Process the message
                await self.process_message(msg_data)
                messages_processed += 1

                # Rate limiting and progress
                if self.args.sleep_ms > 0:
                    await asyncio.sleep(self.args.sleep_ms / 1000)

                if messages_processed % 100 == 0:
                    logger.info(
                        f"Processed {messages_processed} messages from {chat_info['title']}"
                    )

        except Exception as e:
            logger.error(f"Error processing chat {chat_info['title']}: {e}")
            raise

        logger.info(
            f"Completed chat {chat_info['title']}: {messages_processed} messages processed"
        )

        return messages_processed

    async def process_message(self, msg_data: Dict[str, Any]):
        """Process a single message into chunks and index them."""
        chat_id = msg_data["chat_id"]
        message_id = msg_data["message_id"]

        # Check if we already have chunks for this message
        existing_chunks = await self.db.get_existing_chunks(chat_id, message_id)

        # If message hasn't been edited, skip reprocessing
        if existing_chunks and not self._message_needs_update(
            msg_data, existing_chunks
        ):
            logger.debug(f"Skipping unchanged message {message_id}")
            return

        # Get reply context if needed
        reply_text = None
        if msg_data.get("reply_to_msg_id"):
            reply_msg = await self.tg_client.get_message_by_id(
                msg_data.get("entity"), msg_data["reply_to_msg_id"]
            )
            if reply_msg and hasattr(reply_msg, "text"):
                reply_text = reply_msg.text

        # Normalize and compose message text
        text, bm25_text, has_link = normalize_text(msg_data["text"])
        header = create_header(
            msg_data.get("sender"),
            msg_data.get("sender_username"),
            msg_data["message_date"],
        )

        composed_text = compose_message_with_reply(
            text, reply_text, settings.reply_context_tokens
        )

        # Create chunks
        chunks = self.chunker.chunk_text(composed_text, header)

        if not chunks:
            logger.warning(f"No chunks created for message {message_id}")
            return

        # Process each chunk
        chunk_objects = []
        texts_to_embed = []

        for chunk_idx, (full_text, chunk_bm25_text) in enumerate(chunks):
            # Create chunk ID
            chunk_id = (
                f"{chat_id}:{message_id}:{chunk_idx}:v{settings.chunking_version}"
            )

            # Compute text hash for caching
            text_hash = hashlib.sha256(
                f"{full_text}|{settings.embed_model}|{settings.chunking_version}|{settings.preprocess_version}".encode()
            ).hexdigest()

            # Create chunk object
            chunk_obj = Chunk(
                chunk_id=chunk_id,
                chat_id=chat_id,
                message_id=message_id,
                chunk_idx=chunk_idx,
                text_hash=text_hash,
                message_date=msg_data["message_date"],
                edit_date=msg_data.get("edit_date"),
                sender=msg_data.get("sender"),
                sender_username=msg_data.get("sender_username"),
                chat_username=msg_data.get("chat_username"),
                chat_type=msg_data.get("chat_type"),
                thread_id=msg_data.get("thread_id"),
                has_link=has_link,
            )

            chunk_objects.append(chunk_obj)
            texts_to_embed.append(full_text)

        # Get embeddings
        embeddings = await self.embedder.embed_texts(texts_to_embed, self.args.dry_run)

        if self.args.dry_run:
            logger.info(
                f"DRY RUN: Would process {len(chunks)} chunks for message {message_id}"
            )
            return

        # Create Vespa documents
        vespa_docs = []
        for chunk_obj, (text_hash, vector) in zip(chunk_objects, embeddings):
            # Determine which vector field to use based on embedding dimensions
            vector_dict = {"values": vector}
            if settings.embed_dimensions == 1536:
                vector_small = vector_dict
                vector_large = None
            elif settings.embed_dimensions == 3072:
                vector_small = None
                vector_large = vector_dict
            else:
                raise ValueError(
                    f"Unsupported embedding dimension: {settings.embed_dimensions}. Only 1536 and 3072 are supported."
                )

            doc = VespaDocument(
                id=chunk_obj.chunk_id,
                chat_id=chunk_obj.chat_id,
                message_id=chunk_obj.message_id,
                chunk_idx=chunk_obj.chunk_idx,
                source_title=msg_data.get("source_title"),
                sender=chunk_obj.sender,
                sender_username=chunk_obj.sender_username,
                chat_username=chunk_obj.chat_username,
                chat_type=chunk_obj.chat_type,
                message_date=chunk_obj.message_date,
                edit_date=chunk_obj.edit_date,
                thread_id=chunk_obj.thread_id,
                has_link=chunk_obj.has_link,
                text=texts_to_embed[chunk_obj.chunk_idx],
                bm25_text=bm25_text,
                vector_small=vector_small,
                vector_large=vector_large,
            )
            vespa_docs.append(doc)

        # Store in database
        for chunk_obj in chunk_objects:
            await self.db.upsert_chunk(chunk_obj)

        # Feed to Vespa
        success_count = await self.vespa_client.feed_documents(vespa_docs)

        self.metrics.messages_indexed += 1
        self.metrics.chunks_written += len(chunk_objects)

        logger.debug(
            f"Processed message {message_id}: {len(chunks)} chunks, {success_count} fed to Vespa"
        )

    def _message_needs_update(
        self, msg_data: Dict[str, Any], existing_chunks: List[Chunk]
    ) -> bool:
        """Check if message needs to be reprocessed."""
        if not existing_chunks:
            return True

        # Check if edit date is newer
        edit_date = msg_data.get("edit_date")
        if edit_date:
            for chunk in existing_chunks:
                if not chunk.edit_date or edit_date > chunk.edit_date:
                    return True

        return False

    def print_metrics(self):
        """Print final processing metrics."""
        total_metrics = IndexerMetrics(
            messages_scanned=self.metrics.messages_scanned,
            messages_indexed=self.metrics.messages_indexed,
            chunks_written=self.metrics.chunks_written,
            embed_calls=self.embedder.metrics.embed_calls,
            embed_cached_hits=self.embedder.metrics.embed_cached_hits,
            embed_cached_misses=self.embedder.metrics.embed_cached_misses,
            vespa_feed_success=self.vespa_client.metrics.vespa_feed_success,
            vespa_feed_retries=self.vespa_client.metrics.vespa_feed_retries,
            vespa_feed_failures=self.vespa_client.metrics.vespa_feed_failures,
            total_tokens=self.embedder.metrics.total_tokens,
            cost_estimate=self.embedder.metrics.cost_estimate,
        )

        # Calculate cache hit rate
        total_embed_requests = (
            total_metrics.embed_cached_hits + total_metrics.embed_cached_misses
        )
        cache_hit_rate = (
            (total_metrics.embed_cached_hits / total_embed_requests * 100)
            if total_embed_requests > 0
            else 0
        )

        logger.info("=" * 60)
        logger.info("INDEXING COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Messages scanned: {total_metrics.messages_scanned:,}")
        logger.info(f"Messages indexed: {total_metrics.messages_indexed:,}")
        logger.info(f"Chunks written: {total_metrics.chunks_written:,}")
        logger.info(f"Cache hit rate: {cache_hit_rate:.1f}%")
        logger.info(f"Embedding tokens: {total_metrics.total_tokens:,}")
        logger.info(f"Estimated cost: ${total_metrics.cost_estimate:.4f}")
        logger.info(
            f"Vespa feeds: {total_metrics.vespa_feed_success:,} success, {total_metrics.vespa_feed_failures:,} failures"
        )
        logger.info("=" * 60)


async def run_daemon():
    """Run daemon mode (placeholder for Phase 2)."""
    logger.info("Daemon mode not fully implemented in Phase 2")
    logger.info("This is a skeleton that will be expanded in later phases")

    # Placeholder daemon loop
    while True:
        logger.info("Daemon heartbeat - waiting for updates...")
        await asyncio.sleep(60)


def setup_logging(log_level: str):
    """Setup logging configuration."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def parse_args() -> CLIArgs:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Telegram RAG Indexer")

    parser.add_argument("--once", action="store_true", help="Run one-shot indexing")
    parser.add_argument(
        "--chats",
        type=str,
        help="Comma-separated chat names/IDs (optional - defaults to all chats)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Days of history to fetch (default: entire history)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Estimate costs without calling APIs"
    )
    parser.add_argument(
        "--limit-messages", type=int, help="Limit number of messages (for testing)"
    )
    parser.add_argument(
        "--embed-batch-size", type=int, help="Override embedding batch size"
    )
    parser.add_argument(
        "--embed-concurrency", type=int, help="Override embedding concurrency"
    )
    parser.add_argument(
        "--sleep-ms", type=int, default=0, help="Sleep between messages (ms)"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )

    args = parser.parse_args()

    return CLIArgs(
        once=args.once,
        chats=args.chats,
        days=args.days,
        dry_run=args.dry_run,
        limit_messages=args.limit_messages,
        embed_batch_size=args.embed_batch_size,
        embed_concurrency=args.embed_concurrency,
        sleep_ms=args.sleep_ms,
        log_level=args.log_level,
    )


async def main():
    """Main entry point."""
    args = parse_args()
    setup_logging(args.log_level)

    logger.info("Starting Telegram RAG Indexer")
    logger.info(f"Mode: {'One-shot' if args.once else 'Daemon'}")

    if args.once:
        indexer = TelegramIndexer(args)
        try:
            await indexer.initialize()
            await indexer.run_once()
        except Exception as e:
            logger.error(f"Indexing failed: {e}")
            raise
        finally:
            await indexer.cleanup()
    else:
        await run_daemon()


def entrypoint():
    """Entry point for setuptools."""
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
