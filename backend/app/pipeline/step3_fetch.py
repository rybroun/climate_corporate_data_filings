"""
Step 3: Document discovery and storage.

Discovers sustainability documents for a company, deduplicates by content hash,
and inserts SOURCE_DOCUMENT rows via the Supabase client.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from app.services.discovery_agent import discover_documents

logger = logging.getLogger(__name__)


async def fetch_documents(
    company_id: str,
    company_name: str,
    website: str | None,
    pool,
) -> list[dict]:
    """Discover and store sustainability documents for a company.

    Parameters
    ----------
    company_id:
        Internal company UUID.
    company_name:
        The company's canonical name for search queries.
    website:
        The company's official website URL, if known.
    pool:
        SupabasePool instance (or None for mock mode).

    Returns
    -------
    List of source document record dicts with keys:
        source_document_id, company_id, content_hash, original_url,
        source_type, file_size_bytes, page_count, file_bytes (transient).
    """
    # Discover documents
    discovered = await discover_documents(company_name, website, company_id)
    logger.info("Discovered %d documents for %s", len(discovered), company_name)

    source_docs: list[dict] = []

    for doc in discovered:
        # Check dedup if we have a pool and a content hash
        if pool is not None and doc.content_hash:
            try:
                existing = pool.select("source_document", content_hash=doc.content_hash)
                if existing:
                    logger.info(
                        "Skipping duplicate document (hash=%s): %s",
                        doc.content_hash[:12],
                        doc.title,
                    )
                    continue
            except Exception as e:
                logger.warning("Dedup check failed: %s", e)

        # Build source document record
        source_document_id = str(uuid.uuid4())
        storage_path = (
            f"{company_id}/{doc.source_type}/{datetime.now(timezone.utc).year}"
            f"/{doc.content_hash or source_document_id}.pdf"
        )

        record = {
            "source_document_id": source_document_id,
            "company_id": company_id,
            "content_hash": doc.content_hash,
            "storage_bucket": "sustainability-sources",
            "storage_path": storage_path,
            "original_url": doc.original_url or doc.url,
            "source_type": doc.source_type,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "file_size_bytes": doc.file_size,
            "mime_type": "application/pdf",
            "page_count": None,  # Will be set after parsing
            "is_primary": True,
            "title": doc.title,
            # Transient: carry file bytes for extraction step
            "file_bytes": doc.file_bytes,
        }

        # Insert SOURCE_DOCUMENT row via Supabase
        if pool is not None:
            try:
                # Build the row data without transient fields
                row_data = {
                    "source_document_id": source_document_id,
                    "company_id": company_id,
                    "content_hash": doc.content_hash,
                    "storage_bucket": "sustainability-sources",
                    "storage_path": storage_path,
                    "original_url": doc.original_url or doc.url,
                    "source_type": doc.source_type,
                    "retrieved_at": record["retrieved_at"],
                    "file_size_bytes": doc.file_size,
                    "mime_type": "application/pdf",
                    "is_primary": True,
                }
                result = pool.insert("source_document", row_data, on_conflict="content_hash")
                if result:
                    # Use the ID returned by Supabase (may differ on upsert)
                    record["source_document_id"] = result.get(
                        "source_document_id", source_document_id
                    )
                    logger.info(
                        "Inserted source_document %s: %s",
                        record["source_document_id"][:8],
                        doc.title,
                    )
                else:
                    logger.info(
                        "Inserted source_document %s: %s (no return data)",
                        source_document_id[:8],
                        doc.title,
                    )
            except Exception as e:
                logger.warning("Failed to insert source_document: %s", e)

        source_docs.append(record)

    logger.info(
        "Step 3 complete: %d source documents created for %s",
        len(source_docs),
        company_name,
    )
    return source_docs
