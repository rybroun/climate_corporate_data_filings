"""
Step 4: Extraction orchestration per document.

Parses PDFs, classifies pages, and runs focused extraction passes
(emissions, targets, governance) on each document.
"""

from __future__ import annotations

import logging
from dataclasses import asdict

from app.services.pdf_parser import parse_pdf, PageContent
from app.services.claude_extractor import (
    classify_pages,
    extract_emissions,
    extract_targets,
    extract_governance,
    EmissionsExtraction,
    TargetExtraction,
    GovernanceExtraction,
)

logger = logging.getLogger(__name__)


def _get_pages_for_category(
    all_pages: list[PageContent],
    page_numbers: list[int],
) -> list[PageContent]:
    """Filter pages to only those in the given page number list."""
    if not page_numbers:
        return all_pages[:10]  # Fallback: use first 10 pages
    page_set = set(page_numbers)
    return [p for p in all_pages if p.page_number in page_set]


async def extract_from_documents(
    source_docs: list[dict],
    company_id: str,
    pool,
) -> dict:
    """Run extraction pipeline on all source documents.

    For each document:
    1. Parse PDF bytes with PyMuPDF
    2. Classify pages by content type
    3. Run extraction passes (emissions, targets, governance)

    Parameters
    ----------
    source_docs:
        List of source document records from step3_fetch.
        Each should have 'file_bytes' and 'source_document_id'.
    company_id:
        Internal company UUID.
    pool:
        asyncpg connection pool (or None for mock mode).

    Returns
    -------
    Aggregated extraction results dict with keys:
        emissions, targets, governance, documents_processed, data_points_extracted.
    """
    all_emissions: list[dict] = []
    all_targets: list[dict] = []
    all_governance: list[dict] = []
    documents_processed = 0
    data_points = 0

    for doc in source_docs:
        source_doc_id = doc.get("source_document_id", "unknown")
        title = doc.get("title", "Unknown Document")
        file_bytes = doc.get("file_bytes")

        if file_bytes is None:
            logger.info(
                "Skipping document %s (%s) -- no file bytes available",
                source_doc_id[:8],
                title,
            )
            continue

        logger.info("Extracting from document: %s (%s)", title, source_doc_id[:8])

        # Step 4a: Parse PDF
        try:
            parsed = parse_pdf(file_bytes)
            logger.info(
                "Parsed %d pages from %s",
                parsed.page_count,
                title,
            )

            # Update page_count in the source doc record
            doc["page_count"] = parsed.page_count

            # Update page_count in DB if pool available
            if pool is not None:
                try:
                    await pool.execute(
                        "UPDATE source_document SET page_count = $1, updated_at = NOW() WHERE source_document_id = $2::uuid",
                        parsed.page_count,
                        source_doc_id,
                    )
                except Exception as e:
                    logger.warning("Failed to update page_count: %s", e)

        except Exception as e:
            logger.error("Failed to parse PDF %s: %s", title, e)
            continue

        # Step 4b: Classify pages
        try:
            page_map = await classify_pages(parsed.pages)
            logger.info(
                "Page classification: emissions=%s, targets=%s, governance=%s",
                page_map.get("emissions_data", []),
                page_map.get("targets", []),
                page_map.get("governance", []),
            )
        except Exception as e:
            logger.warning("Page classification failed for %s: %s", title, e)
            page_map = {}

        # Step 4c: Emissions extraction
        try:
            emissions_pages = _get_pages_for_category(
                parsed.pages, page_map.get("emissions_data", [])
            )
            emissions = await extract_emissions(emissions_pages)
            emissions_dict = asdict(emissions)
            emissions_dict["source_document_id"] = source_doc_id
            emissions_dict["document_title"] = title
            all_emissions.append(emissions_dict)

            n_items = len(emissions.line_items)
            data_points += n_items + 5  # 5 for scope values + metadata
            logger.info(
                "Extracted emissions: year=%s, scope1=%s, scope3=%s, %d line items",
                emissions.reporting_year,
                emissions.scope_1_tco2e,
                emissions.scope_3_total_tco2e,
                n_items,
            )
        except Exception as e:
            logger.error("Emissions extraction failed for %s: %s", title, e)

        # Step 4d: Targets extraction
        try:
            target_pages = _get_pages_for_category(
                parsed.pages, page_map.get("targets", [])
            )
            targets = await extract_targets(target_pages)
            for t in targets:
                t_dict = asdict(t)
                t_dict["source_document_id"] = source_doc_id
                all_targets.append(t_dict)
            data_points += len(targets) * 5
            logger.info("Extracted %d targets from %s", len(targets), title)
        except Exception as e:
            logger.error("Targets extraction failed for %s: %s", title, e)

        # Step 4e: Governance extraction
        try:
            governance_pages = _get_pages_for_category(
                parsed.pages, page_map.get("governance", [])
            )
            governance = await extract_governance(governance_pages)
            gov_dict = asdict(governance)
            gov_dict["source_document_id"] = source_doc_id
            all_governance.append(gov_dict)
            data_points += 5
            logger.info("Extracted governance signals from %s", title)
        except Exception as e:
            logger.error("Governance extraction failed for %s: %s", title, e)

        documents_processed += 1

    results = {
        "emissions": all_emissions,
        "targets": all_targets,
        "governance": all_governance,
        "documents_processed": documents_processed,
        "data_points_extracted": data_points,
    }

    logger.info(
        "Step 4 complete: processed %d documents, extracted %d data points "
        "(%d emissions, %d targets, %d governance)",
        documents_processed,
        data_points,
        len(all_emissions),
        len(all_targets),
        len(all_governance),
    )

    return results
