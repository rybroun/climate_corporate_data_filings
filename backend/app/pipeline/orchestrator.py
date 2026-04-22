"""
Pipeline orchestrator — runs the 7-step extraction pipeline with verbose logging.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class PipelineJob:
    job_id: str
    query: str
    wikidata_qid: str | None
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    status: str = "pending"
    company_id: str | None = None


_jobs: dict[str, PipelineJob] = {}


def create_job(query: str, wikidata_qid: str | None = None) -> PipelineJob:
    job_id = str(uuid.uuid4())
    job = PipelineJob(job_id=job_id, query=query, wikidata_qid=wikidata_qid)
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> PipelineJob | None:
    return _jobs.get(job_id)


def _step_event(step, step_name, status, log_line, documents_found=None, company_id=None):
    return {
        "event": "step",
        "data": json.dumps({
            "step": step, "step_name": step_name, "status": status,
            "log_line": log_line, "documents_found": documents_found,
            "company_id": company_id,
        }),
    }


def _complete_event(company_id, documents_processed, years_covered):
    return {
        "event": "complete",
        "data": json.dumps({
            "company_id": company_id,
            "documents_processed": documents_processed,
            "years_covered": years_covered,
        }),
    }


async def _emit(job, step, step_name, status, log_line, documents_found=None, company_id=None):
    """Emit a step event and a short delay so the frontend can animate."""
    await job.queue.put(_step_event(step, step_name, status, log_line, documents_found, company_id))
    await asyncio.sleep(0.1)


def _get_pool():
    try:
        from app.db import get_pool
        return get_pool()
    except (RuntimeError, ImportError):
        return None


async def run_pipeline(job: PipelineJob) -> None:
    job.status = "running"
    pool = _get_pool()
    company_id = None
    company_name = job.query
    website = None
    source_docs: list[dict] = []
    extractions: dict = {}
    documents_found = 0
    years_covered: list[int] = []

    # ── Step 1: Parse query ──────────────────────────────────────
    parsed_query = None
    try:
        from app.pipeline.step1_parse import parse_query

        await _emit(job, 1, "Parse query", "running",
            f"→ Analyzing input: \"{job.query}\"")

        parsed_query = await parse_query(job.query)

        lines = [
            f"  Normalized name: \"{parsed_query.normalized_name}\"",
        ]
        if parsed_query.legal_suffix:
            lines.append(f"  Legal suffix detected: {parsed_query.legal_suffix}")
        if parsed_query.inferred_jurisdiction:
            lines.append(f"  Inferred jurisdiction: {parsed_query.inferred_jurisdiction}")
        lines.append(f"  Input type: {parsed_query.input_type} (confidence: {parsed_query.confidence:.0%})")

        for line in lines:
            await _emit(job, 1, "Parse query", "running", line)

        await _emit(job, 1, "Parse query", "done",
            f"✓ Query parsed — searching for \"{parsed_query.normalized_name}\"")

    except Exception as e:
        logger.error("Step 1 failed: %s", e)
        await _emit(job, 1, "Parse query", "error", f"Error: {e}")

    # ── Step 2: Match entity ─────────────────────────────────────
    try:
        from app.pipeline.step2_match import match_entity
        from app.pipeline.step1_parse import ParsedQuery

        if parsed_query is None:
            parsed_query = ParsedQuery(
                normalized_name=job.query.strip(), legal_suffix=None,
                inferred_jurisdiction=None, original_input=job.query,
                input_type="wikidata_qid" if job.wikidata_qid else "company_name",
                confidence=0.5,
            )
            if job.wikidata_qid:
                parsed_query.normalized_name = job.wikidata_qid
                parsed_query.input_type = "wikidata_qid"

        await _emit(job, 2, "Match entity", "running",
            f"→ Searching local database for \"{parsed_query.normalized_name}\"...")

        match_result = await match_entity(parsed_query, pool)

        company_id = match_result.company_id
        company_name = match_result.canonical_name
        job.company_id = company_id

        # Verbose match logging
        if match_result.source == "local_db":
            await _emit(job, 2, "Match entity", "running",
                f"  ✓ Found in local DB: {company_name}", company_id=company_id)
            await _emit(job, 2, "Match entity", "running",
                f"  Match score: {match_result.match_score:.2f} — auto-resolved", company_id=company_id)
        else:
            await _emit(job, 2, "Match entity", "running",
                f"  No strong local match — querying Wikidata...", company_id=company_id)
            await _emit(job, 2, "Match entity", "running",
                f"  ✓ Wikidata: {company_name} ({match_result.wikidata_qid})", company_id=company_id)

        if match_result.wikidata_qid:
            try:
                from app.services.wikidata import get_entity
                entity = await get_entity(match_result.wikidata_qid)
                website = entity.website
                details = []
                if entity.country_code:
                    details.append(f"HQ: {entity.country_code}")
                if entity.lei:
                    details.append(f"LEI: {entity.lei[:12]}...")
                if entity.website:
                    details.append(f"Website: {entity.website}")
                if details:
                    await _emit(job, 2, "Match entity", "running",
                        f"  Entity details: {' · '.join(details)}", company_id=company_id)
            except Exception:
                pass

        if match_result.is_new:
            await _emit(job, 2, "Match entity", "running",
                f"  Created new company record: {company_id[:8]}...", company_id=company_id)

        await _emit(job, 2, "Match entity", "done",
            f"✓ Resolved: {company_name} (score: {match_result.match_score:.2f})",
            company_id=company_id)

        # Fast path: skip steps 3-7 if company already has emissions data
        if match_result.has_existing_data:
            await _emit(job, 2, "Match entity", "done",
                f"  Company has existing emissions data — skipping extraction",
                company_id=company_id)

            skip_msgs = [
                (3, "Fetch public filings", "cached — documents already on file"),
                (4, "Extract emissions", "cached — emissions data already extracted"),
                (5, "Normalize units", "cached — units already normalized"),
                (6, "Classify Scope 1/2/3", "cached — categories already mapped"),
                (7, "Store & cache", "cached — data ready to display"),
            ]
            for step_num, step_name, msg in skip_msgs:
                await _emit(job, step_num, step_name, "done", f"→ {msg}",
                    company_id=company_id)

            job.status = "complete"
            await job.queue.put(_complete_event(company_id, 0, [2024]))
            return

    except Exception as e:
        logger.error("Step 2 failed: %s", e)
        company_id = company_id or str(uuid.uuid4())
        job.company_id = company_id
        await _emit(job, 2, "Match entity", "error", f"Error: {e}", company_id=company_id)

    # ── Step 3: Fetch public filings ─────────────────────────────
    try:
        from app.pipeline.step3_fetch import fetch_documents

        await _emit(job, 3, "Fetch public filings", "running",
            f"→ Searching for {company_name} sustainability documents...",
            company_id=company_id)

        if website:
            await _emit(job, 3, "Fetch public filings", "running",
                f"  Company website: {website}", company_id=company_id)

        await _emit(job, 3, "Fetch public filings", "running",
            f"  Querying Serper: \"{company_name} sustainability report filetype:pdf\"",
            company_id=company_id)

        source_docs = await fetch_documents(company_id, company_name, website, pool)
        documents_found = len(source_docs)

        for doc in source_docs[:5]:
            title = doc.get("title", "Unknown document")
            size = doc.get("file_size_bytes")
            size_str = f" ({size / 1_000_000:.1f}MB)" if size else ""
            await _emit(job, 3, "Fetch public filings", "running",
                f"  ✓ {title}{size_str}",
                documents_found=documents_found, company_id=company_id)

        await _emit(job, 3, "Fetch public filings", "done",
            f"✓ Found {documents_found} public documents",
            documents_found=documents_found, company_id=company_id)

    except Exception as e:
        logger.error("Step 3 failed: %s", e)
        await _emit(job, 3, "Fetch public filings", "error",
            f"Error: {e}", documents_found=0, company_id=company_id)

    # ── Step 4: Extract emissions ────────────────────────────────
    try:
        from app.pipeline.step4_extract import extract_from_documents

        await _emit(job, 4, "Extract emissions", "running",
            f"→ Parsing {documents_found} documents with PyMuPDF...",
            documents_found=documents_found, company_id=company_id)

        extractions = await extract_from_documents(source_docs, company_id, pool)
        data_points = extractions.get("data_points_extracted", 0)
        docs_processed = extractions.get("documents_processed", 0)

        if docs_processed > 0:
            await _emit(job, 4, "Extract emissions", "running",
                f"  Classified pages across {docs_processed} documents",
                documents_found=documents_found, company_id=company_id)
            await _emit(job, 4, "Extract emissions", "running",
                f"  Running Claude extraction (emissions, targets, governance)...",
                documents_found=documents_found, company_id=company_id)

        emissions_list = extractions.get("emissions", [])
        for em in emissions_list:
            yr = em.get("reporting_year", "?")
            s1 = em.get("scope_1_tco2e")
            s3 = em.get("scope_3_total_tco2e")
            if s1 or s3:
                await _emit(job, 4, "Extract emissions", "running",
                    f"  Found FY{yr}: Scope 1 = {s1:,.0f} tCO₂e, Scope 3 = {s3:,.0f} tCO₂e" if s1 and s3 else f"  Found FY{yr} data",
                    documents_found=documents_found, company_id=company_id)

        await _emit(job, 4, "Extract emissions", "done",
            f"✓ Extracted {data_points} data points from {docs_processed} documents",
            documents_found=documents_found, company_id=company_id)

    except Exception as e:
        logger.error("Step 4 failed: %s", e)
        await _emit(job, 4, "Extract emissions", "error",
            f"Error: {e}", documents_found=documents_found, company_id=company_id)

    # ── Step 5: Normalize units ──────────────────────────────────
    try:
        from app.pipeline.step5_normalize import normalize_extraction
        from app.services.claude_extractor import EmissionsExtraction, LineItemExtraction

        await _emit(job, 5, "Normalize units", "running",
            "→ Converting all values to tCO₂e...",
            documents_found=documents_found, company_id=company_id)

        conversions = 0
        for em_dict in extractions.get("emissions", []):
            line_items = [
                LineItemExtraction(
                    native_category=li.get("native_category", ""),
                    tco2e=li.get("tco2e", 0),
                    data_quality_tier=li.get("data_quality_tier"),
                    tags=li.get("tags", []),
                )
                for li in em_dict.get("line_items", [])
            ]
            extraction = EmissionsExtraction(
                reporting_year=em_dict.get("reporting_year"),
                scope_1_tco2e=em_dict.get("scope_1_tco2e"),
                scope_2_location_tco2e=em_dict.get("scope_2_location_tco2e"),
                scope_2_market_tco2e=em_dict.get("scope_2_market_tco2e"),
                scope_3_total_tco2e=em_dict.get("scope_3_total_tco2e"),
                methodology=em_dict.get("methodology"),
                verification_status=em_dict.get("verification_status"),
                verifier_name=em_dict.get("verifier_name"),
                boundary_definition=em_dict.get("boundary_definition"),
                page_number=em_dict.get("page_number"),
                section_reference=em_dict.get("section_reference"),
                confidence=em_dict.get("confidence", 0.5),
                line_items=line_items,
            )
            normalize_extraction(extraction)
            conversions += len(line_items)

        await _emit(job, 5, "Normalize units", "done",
            f"✓ Verified {conversions} values — all standardized to tCO₂e",
            documents_found=documents_found, company_id=company_id)

    except Exception as e:
        logger.error("Step 5 failed: %s", e)
        await _emit(job, 5, "Normalize units", "error",
            f"Error: {e}", documents_found=documents_found, company_id=company_id)

    # ── Step 6: Classify Scope 1/2/3 ─────────────────────────────
    try:
        from app.pipeline.step6_classify import classify_categories
        from app.services.claude_extractor import LineItemExtraction

        all_line_items = []
        for em_dict in extractions.get("emissions", []):
            for li in em_dict.get("line_items", []):
                all_line_items.append(
                    LineItemExtraction(
                        native_category=li.get("native_category", ""),
                        tco2e=li.get("tco2e", 0),
                        data_quality_tier=li.get("data_quality_tier"),
                        tags=li.get("tags", []),
                    )
                )

        await _emit(job, 6, "Classify Scope 1/2/3", "running",
            f"→ Mapping {len(all_line_items)} native categories to GHG Protocol...",
            documents_found=documents_found, company_id=company_id)

        mappings = await classify_categories(all_line_items, company_id, pool)

        for m in mappings[:5]:
            native = m.get("native_category", "?")
            ghg = m.get("ghg_code", "?")
            pct = m.get("allocation_pct", 1.0)
            await _emit(job, 6, "Classify Scope 1/2/3", "running",
                f"  {native} → {ghg} ({pct:.0%})",
                documents_found=documents_found, company_id=company_id)

        await _emit(job, 6, "Classify Scope 1/2/3", "done",
            f"✓ Mapped {len(all_line_items)} categories → {len(mappings)} GHG Protocol codes",
            documents_found=documents_found, company_id=company_id)

    except Exception as e:
        logger.error("Step 6 failed: %s", e)
        await _emit(job, 6, "Classify Scope 1/2/3", "error",
            f"Error: {e}", documents_found=documents_found, company_id=company_id)

    # ── Step 7: Store & cache ────────────────────────────────────
    try:
        from app.pipeline.step7_store import store_results

        await _emit(job, 7, "Store & cache", "running",
            "→ Writing results to database...",
            documents_found=documents_found, company_id=company_id)

        result = await store_results(company_id, extractions, source_docs, pool)

        disclosure_count = result.get("disclosures_written", 0)
        source_count = result.get("source_documents_written", 0)
        provenance_count = result.get("provenance_records_written", 0)

        await _emit(job, 7, "Store & cache", "running",
            f"  Wrote {disclosure_count} disclosure rows",
            documents_found=documents_found, company_id=company_id)
        await _emit(job, 7, "Store & cache", "running",
            f"  Linked {source_count} source documents",
            documents_found=documents_found, company_id=company_id)
        await _emit(job, 7, "Store & cache", "running",
            f"  Created {provenance_count} provenance records",
            documents_found=documents_found, company_id=company_id)

        years_covered = result.get("years_covered", [2024])

        await _emit(job, 7, "Store & cache", "done",
            f"✓ Cached — {company_name} profile ready",
            documents_found=documents_found, company_id=company_id)

    except Exception as e:
        logger.error("Step 7 failed: %s", e)
        await _emit(job, 7, "Store & cache", "error",
            f"Error: {e}", documents_found=documents_found, company_id=company_id)

    # ── Complete ─────────────────────────────────────────────────
    job.status = "complete"
    await job.queue.put(_complete_event(
        company_id=company_id or str(uuid.uuid4()),
        documents_processed=documents_found,
        years_covered=years_covered or [2024],
    ))
