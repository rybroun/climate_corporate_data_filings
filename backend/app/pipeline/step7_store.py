"""
Step 7: Write-back to all data model tables.

Writes extraction results in dependency order using upserts.
Falls back to a mock summary when no DB pool is available.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mock_summary() -> dict:
    """Return a mock write-back summary for testing without DB."""
    return {
        "company_updated": True,
        "emissions_disclosures": 3,
        "emissions_line_items": 12,
        "line_item_tags": 4,
        "category_mappings": 11,
        "emissions_targets": 3,
        "data_provenance": 18,
        "total_rows": 52,
    }


async def store_results(
    company_id: str,
    extractions: dict,
    source_docs: list[dict],
    pool,
) -> dict:
    """Write extraction results to all data model tables.

    Writes in dependency order using INSERT ... ON CONFLICT DO UPDATE
    for idempotent upserts.

    Parameters
    ----------
    company_id:
        Internal company UUID.
    extractions:
        Aggregated extraction results from step4_extract, with keys:
        emissions, targets, governance, documents_processed, data_points_extracted.
    source_docs:
        List of source document records from step3_fetch.
    pool:
        asyncpg connection pool (or None for mock mode).

    Returns
    -------
    Summary dict with row counts per table.
    """
    if pool is None:
        logger.info("No DB pool available, returning mock write-back summary")
        return _mock_summary()

    summary = {
        "company_updated": False,
        "emissions_disclosures": 0,
        "emissions_line_items": 0,
        "line_item_tags": 0,
        "category_mappings": 0,
        "emissions_targets": 0,
        "data_provenance": 0,
        "total_rows": 0,
    }

    now = _now()

    # -----------------------------------------------------------------------
    # 1. Update COMPANY governance fields if extracted
    # -----------------------------------------------------------------------
    governance_list = extractions.get("governance", [])
    if governance_list:
        # Use the highest-confidence governance extraction
        best_gov = max(governance_list, key=lambda g: g.get("confidence", 0))
        try:
            await pool.execute(
                """
                UPDATE company SET
                    exec_comp_tied_to_climate = COALESCE($2, exec_comp_tied_to_climate),
                    exec_comp_pct = COALESCE($3, exec_comp_pct),
                    board_oversight = COALESCE($4, board_oversight),
                    board_committee_name = COALESCE($5, board_committee_name),
                    has_transition_plan = COALESCE($6, has_transition_plan),
                    governance_last_verified_at = $7,
                    updated_at = $7
                WHERE company_id = $1::uuid
                """,
                company_id,
                best_gov.get("exec_comp_tied_to_climate"),
                best_gov.get("exec_comp_pct"),
                best_gov.get("board_oversight"),
                best_gov.get("board_committee_name"),
                best_gov.get("has_transition_plan"),
                now,
            )
            summary["company_updated"] = True
            logger.info("Updated COMPANY governance fields for %s", company_id[:8])
        except Exception as e:
            logger.warning("Failed to update COMPANY governance: %s", e)

    # -----------------------------------------------------------------------
    # 2. EMISSIONS_DISCLOSURE -- one row per (company, source_doc, year)
    # -----------------------------------------------------------------------
    emissions_list = extractions.get("emissions", [])
    for em in emissions_list:
        disclosure_id = str(uuid.uuid4())
        source_doc_id = em.get("source_document_id")
        reporting_year = em.get("reporting_year")

        if not reporting_year:
            logger.warning("Skipping emission with no reporting_year")
            continue

        try:
            await pool.execute(
                """
                INSERT INTO emissions_disclosure (
                    disclosure_id, company_id, source_document_id, reporting_year,
                    scope_1_tco2e, scope_2_location_tco2e, scope_2_market_tco2e,
                    scope_3_total_tco2e, methodology, verification_status,
                    verifier_name, source_authority, boundary_definition,
                    page_number, section_reference,
                    last_verified_at, is_withdrawn,
                    created_at, updated_at
                ) VALUES (
                    $1::uuid, $2::uuid, $3::uuid, $4,
                    $5, $6, $7, $8, $9, $10,
                    $11, $12, $13, $14, $15,
                    $16, false, $16, $16
                )
                ON CONFLICT (company_id, source_document_id, reporting_year)
                DO UPDATE SET
                    scope_1_tco2e = EXCLUDED.scope_1_tco2e,
                    scope_2_location_tco2e = EXCLUDED.scope_2_location_tco2e,
                    scope_2_market_tco2e = EXCLUDED.scope_2_market_tco2e,
                    scope_3_total_tco2e = EXCLUDED.scope_3_total_tco2e,
                    methodology = EXCLUDED.methodology,
                    verification_status = EXCLUDED.verification_status,
                    verifier_name = EXCLUDED.verifier_name,
                    boundary_definition = EXCLUDED.boundary_definition,
                    page_number = EXCLUDED.page_number,
                    section_reference = EXCLUDED.section_reference,
                    last_verified_at = EXCLUDED.last_verified_at,
                    updated_at = EXCLUDED.updated_at
                RETURNING disclosure_id
                """,
                disclosure_id,
                company_id,
                source_doc_id,
                reporting_year,
                em.get("scope_1_tco2e"),
                em.get("scope_2_location_tco2e"),
                em.get("scope_2_market_tco2e"),
                em.get("scope_3_total_tco2e"),
                em.get("methodology", "ghg_protocol_corporate"),
                em.get("verification_status", "none"),
                em.get("verifier_name"),
                "self_reported",  # default source_authority
                em.get("boundary_definition"),
                em.get("page_number"),
                em.get("section_reference"),
                now,
            )
            summary["emissions_disclosures"] += 1
            logger.info(
                "Wrote disclosure: year=%d, doc=%s",
                reporting_year,
                source_doc_id[:8] if source_doc_id else "none",
            )

            # -----------------------------------------------------------
            # 3. EMISSIONS_LINE_ITEM -- one row per (disclosure, native_category)
            # -----------------------------------------------------------
            line_items = em.get("line_items", [])
            for li in line_items:
                line_item_id = str(uuid.uuid4())
                try:
                    await pool.execute(
                        """
                        INSERT INTO emissions_line_item (
                            line_item_id, disclosure_id, company_id,
                            reporting_year, native_category, tco2e,
                            data_quality_tier, is_excluded_from_target,
                            is_withdrawn, created_at, updated_at
                        ) VALUES (
                            $1::uuid, $2::uuid, $3::uuid,
                            $4, $5, $6, $7, false, false, $8, $8
                        )
                        ON CONFLICT (disclosure_id, native_category)
                        DO UPDATE SET
                            tco2e = EXCLUDED.tco2e,
                            data_quality_tier = EXCLUDED.data_quality_tier,
                            updated_at = EXCLUDED.updated_at
                        RETURNING line_item_id
                        """,
                        line_item_id,
                        disclosure_id,
                        company_id,
                        reporting_year,
                        li.get("native_category", "Unknown"),
                        li.get("tco2e"),
                        li.get("data_quality_tier"),
                        now,
                    )
                    summary["emissions_line_items"] += 1

                    # -----------------------------------------------
                    # 4. EMISSIONS_LINE_ITEM_TAG -- junction rows
                    # -----------------------------------------------
                    tags = li.get("tags", [])
                    for tag in tags:
                        try:
                            await pool.execute(
                                """
                                INSERT INTO emissions_line_item_tag (
                                    line_item_id, tag_code
                                ) VALUES ($1::uuid, $2)
                                ON CONFLICT DO NOTHING
                                """,
                                line_item_id,
                                tag,
                            )
                            summary["line_item_tags"] += 1
                        except Exception as e:
                            logger.debug("Failed to insert tag %s: %s", tag, e)

                except Exception as e:
                    logger.warning(
                        "Failed to insert line item '%s': %s",
                        li.get("native_category"),
                        e,
                    )

            # -----------------------------------------------------------
            # 7. DATA_PROVENANCE for the disclosure
            # -----------------------------------------------------------
            try:
                await pool.execute(
                    """
                    INSERT INTO data_provenance (
                        provenance_id, record_id, record_table,
                        source_document_id, page_number, section_reference,
                        extraction_date, extraction_method, extractor_version,
                        raw_extraction_payload, confidence, human_verified,
                        created_at, updated_at
                    ) VALUES (
                        $1::uuid, $2::uuid, 'emissions_disclosure',
                        $3::uuid, $4, $5,
                        $6, 'llm_structured', 'v1.0.0',
                        $7::jsonb, $8, false,
                        $9, $9
                    )
                    ON CONFLICT DO NOTHING
                    """,
                    str(uuid.uuid4()),
                    disclosure_id,
                    source_doc_id,
                    em.get("page_number"),
                    em.get("section_reference"),
                    date.today(),
                    json.dumps(em),
                    em.get("confidence", 0.5),
                    now,
                )
                summary["data_provenance"] += 1
            except Exception as e:
                logger.warning("Failed to insert provenance for disclosure: %s", e)

        except Exception as e:
            logger.warning("Failed to insert disclosure for year %s: %s", reporting_year, e)

    # -----------------------------------------------------------------------
    # 6. EMISSIONS_TARGET -- if extracted
    # -----------------------------------------------------------------------
    targets_list = extractions.get("targets", [])
    for t in targets_list:
        target_id = str(uuid.uuid4())
        try:
            scope_coverage = t.get("scope_coverage", [])
            await pool.execute(
                """
                INSERT INTO emissions_target (
                    target_id, company_id, target_type, sbti_status,
                    baseline_year, target_year, reduction_pct,
                    scope_coverage, target_language,
                    last_verified_at, is_withdrawn,
                    created_at, updated_at
                ) VALUES (
                    $1::uuid, $2::uuid, $3, $4,
                    $5, $6, $7,
                    $8, $9,
                    $10, false, $10, $10
                )
                ON CONFLICT (company_id, target_type, baseline_year, target_year)
                DO UPDATE SET
                    sbti_status = EXCLUDED.sbti_status,
                    reduction_pct = EXCLUDED.reduction_pct,
                    scope_coverage = EXCLUDED.scope_coverage,
                    target_language = EXCLUDED.target_language,
                    last_verified_at = EXCLUDED.last_verified_at,
                    updated_at = EXCLUDED.updated_at
                """,
                target_id,
                company_id,
                t.get("target_type", "near_term"),
                t.get("sbti_status"),
                t.get("baseline_year"),
                t.get("target_year"),
                t.get("reduction_pct"),
                scope_coverage,
                t.get("target_language"),
                now,
            )
            summary["emissions_targets"] += 1

            # Provenance for target
            source_doc_id = t.get("source_document_id")
            if source_doc_id:
                try:
                    await pool.execute(
                        """
                        INSERT INTO data_provenance (
                            provenance_id, record_id, record_table,
                            source_document_id, extraction_date,
                            extraction_method, extractor_version,
                            raw_extraction_payload, confidence,
                            human_verified, created_at, updated_at
                        ) VALUES (
                            $1::uuid, $2::uuid, 'emissions_target',
                            $3::uuid, $4,
                            'llm_structured', 'v1.0.0',
                            $5::jsonb, $6,
                            false, $7, $7
                        )
                        ON CONFLICT DO NOTHING
                        """,
                        str(uuid.uuid4()),
                        target_id,
                        source_doc_id,
                        date.today(),
                        json.dumps(t),
                        t.get("confidence", 0.5),
                        now,
                    )
                    summary["data_provenance"] += 1
                except Exception as e:
                    logger.debug("Failed to insert provenance for target: %s", e)

        except Exception as e:
            logger.warning("Failed to insert target: %s", e)

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    summary["total_rows"] = (
        (1 if summary["company_updated"] else 0)
        + summary["emissions_disclosures"]
        + summary["emissions_line_items"]
        + summary["line_item_tags"]
        + summary["category_mappings"]
        + summary["emissions_targets"]
        + summary["data_provenance"]
    )

    logger.info(
        "Step 7 complete: wrote %d total rows "
        "(disclosures=%d, line_items=%d, targets=%d, provenance=%d)",
        summary["total_rows"],
        summary["emissions_disclosures"],
        summary["emissions_line_items"],
        summary["emissions_targets"],
        summary["data_provenance"],
    )

    return summary
