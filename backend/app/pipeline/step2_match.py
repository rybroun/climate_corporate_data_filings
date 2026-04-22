"""
Pipeline Step 2 — Entity Matching.

Resolves a ParsedQuery to a COMPANY row in the database, using local DB
lookup first (fast path) and Wikidata as fallback (cold start).

Persists reranker outputs to ``er_match_log`` and upserts the COMPANY row
with whatever identity fields Wikidata provides.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.pipeline.step1_parse import ParsedQuery
from app.services.wikidata import WikidataEntity, get_entity, search_entities

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class MatchResult:
    company_id: str  # UUID
    canonical_name: str
    is_new: bool  # True if we just created this company
    source: str  # "local_db" | "wikidata"
    match_score: float
    wikidata_qid: str | None
    has_existing_data: bool = False  # True if company already has emissions data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pick_best_wikidata(
    entities: list[WikidataEntity],
    jurisdiction: str | None,
) -> tuple[WikidataEntity | None, float]:
    if not entities:
        return None, 0.0

    scored: list[tuple[WikidataEntity, float]] = []
    for entity in entities:
        score = 0.5
        if entity.ticker:
            score += 0.15
        if entity.lei:
            score += 0.1
        if jurisdiction and entity.country_code:
            if entity.country_code.upper() == jurisdiction.upper():
                score += 0.2
        if entity.website:
            score += 0.05
        scored.append((entity, min(score, 1.0)))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0]


def _entity_to_company_fields(entity: WikidataEntity) -> dict[str, Any]:
    return {
        "canonical_name": entity.label,
        "legal_name": entity.official_name,
        "aliases": entity.aliases,
        "wikidata_qid": entity.qid,
        "ticker": entity.ticker,
        "lei": entity.lei,
        "hq_country": entity.country_code,
        "is_public": entity.ticker is not None,
    }


# ---------------------------------------------------------------------------
# DB operations via Supabase client
# ---------------------------------------------------------------------------

async def _db_lookup_by_qid(pool: Any, qid: str) -> dict[str, Any] | None:
    if pool is None or not getattr(pool, 'available', False):
        return None
    try:
        rows = pool.select("company", wikidata_qid=qid)
        return rows[0] if rows else None
    except Exception:
        logger.warning("DB lookup by QID failed", exc_info=True)
        return None


async def _db_search_companies(pool: Any, name: str, limit: int = 5) -> list[dict[str, Any]]:
    if pool is None or not getattr(pool, 'available', False):
        return []
    try:
        # Try the pg_trgm search function first
        results = pool.rpc("search_companies", {"query": name, "max_results": limit})
        if results:
            return results
        # Fallback to ILIKE
        return pool.select_ilike("company", "canonical_name", f"%{name}%", limit=limit)
    except Exception:
        logger.warning("DB search_companies failed", exc_info=True)
        return []


async def _db_has_emissions(pool: Any, company_id: str) -> bool:
    """Check if a company already has emissions disclosure data."""
    if pool is None or not getattr(pool, 'available', False):
        return False
    try:
        rows = pool.select("emissions_disclosure", company_id=company_id)
        return len(rows) > 0
    except Exception:
        return False


async def _db_log_match(
    pool: Any,
    raw_input: str,
    normalized_input: str,
    candidates: list[dict[str, Any]],
    chosen_company_id: str | None,
    source: str,
) -> None:
    if pool is None or not getattr(pool, 'available', False):
        return
    try:
        pool.insert("er_match_log", {
            "raw_input": raw_input,
            "normalized_input": json.dumps(normalized_input, default=str) if not isinstance(normalized_input, str) else normalized_input,
            "candidates": json.dumps(candidates, default=str),
            "chosen_company_id": chosen_company_id,
            "source": source,
        })
    except Exception:
        logger.warning("Failed to log ER match", exc_info=True)


async def _db_upsert_company(pool: Any, fields: dict[str, Any]) -> str:
    if pool is None or not getattr(pool, 'available', False):
        mock_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, fields.get("canonical_name", "unknown")))
        return mock_id

    try:
        qid = fields.get("wikidata_qid")
        existing = None
        if qid:
            rows = pool.select("company", wikidata_qid=qid)
            existing = rows[0] if rows else None

        if existing:
            company_id = existing["company_id"]
            update_data = {}
            for key in ["canonical_name", "legal_name", "ticker", "lei", "hq_country", "is_public"]:
                if fields.get(key) and not existing.get(key):
                    update_data[key] = fields[key]
            # Merge aliases
            old_aliases = existing.get("aliases") or []
            new_aliases = fields.get("aliases") or []
            merged = list(set(old_aliases + new_aliases))
            if merged != old_aliases:
                update_data["aliases"] = merged
            if update_data:
                pool.table("company").update(update_data).eq("company_id", company_id).execute()
            return str(company_id)
        else:
            result = pool.insert("company", {
                "canonical_name": fields.get("canonical_name"),
                "legal_name": fields.get("legal_name"),
                "aliases": fields.get("aliases", []),
                "wikidata_qid": fields.get("wikidata_qid"),
                "ticker": fields.get("ticker"),
                "lei": fields.get("lei"),
                "hq_country": fields.get("hq_country"),
                "is_public": fields.get("is_public", False),
            })
            if result and "company_id" in result:
                return str(result["company_id"])
            mock_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, fields.get("canonical_name", "unknown")))
            return mock_id
    except Exception:
        logger.error("Failed to upsert company", exc_info=True)
        mock_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, fields.get("canonical_name", "unknown")))
        return mock_id


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def match_entity(parsed: ParsedQuery, pool: Any = None) -> MatchResult:
    """Resolve a ParsedQuery to a company, using local DB then Wikidata fallback."""

    # Path A: Wikidata QID provided directly
    if parsed.input_type == "wikidata_qid":
        qid = parsed.normalized_name
        existing = await _db_lookup_by_qid(pool, qid)
        if existing:
            company_id = str(existing.get("company_id", ""))
            has_data = await _db_has_emissions(pool, company_id)
            await _db_log_match(pool, parsed.original_input, parsed.normalized_name,
                [{"company_id": company_id, "source": "local_db", "score": 1.0}],
                company_id, "local_db")
            return MatchResult(company_id=company_id, canonical_name=existing.get("canonical_name", qid),
                is_new=False, source="local_db", match_score=1.0, wikidata_qid=qid, has_existing_data=has_data)

        try:
            entity = await get_entity(qid)
        except Exception:
            logger.error("Failed to fetch Wikidata entity %s", qid, exc_info=True)
            mock_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, qid))
            return MatchResult(company_id=mock_id, canonical_name=qid, is_new=True,
                source="wikidata", match_score=0.5, wikidata_qid=qid)

        fields = _entity_to_company_fields(entity)
        company_id = await _db_upsert_company(pool, fields)
        await _db_log_match(pool, parsed.original_input, parsed.normalized_name,
            [{"qid": qid, "label": entity.label, "source": "wikidata", "score": 1.0}],
            company_id, "wikidata")
        return MatchResult(company_id=company_id, canonical_name=entity.label or qid,
            is_new=True, source="wikidata", match_score=1.0, wikidata_qid=qid)

    # Path B: Company name search
    name = parsed.normalized_name

    # Step 1: Local DB search
    local_candidates = await _db_search_companies(pool, name)
    if local_candidates:
        top = local_candidates[0]
        top_score = float(top.get("similarity", 0))

        if top_score > 0.3:  # Lowered threshold for Supabase ILIKE fallback
            company_id = str(top.get("company_id", ""))
            has_data = await _db_has_emissions(pool, company_id)
            await _db_log_match(pool, parsed.original_input, name,
                [{"company_id": str(c.get("company_id", "")), "canonical_name": c.get("canonical_name", ""),
                  "similarity": float(c.get("similarity", 0)), "source": "local_db"} for c in local_candidates],
                company_id, "local_db")
            return MatchResult(company_id=company_id, canonical_name=top.get("canonical_name", name),
                is_new=False, source="local_db", match_score=top_score,
                wikidata_qid=top.get("wikidata_qid"), has_existing_data=has_data)

    # Step 2: Wikidata fallback
    try:
        wikidata_results = await search_entities(name)
    except Exception:
        logger.error("Wikidata search failed for %r", name, exc_info=True)
        wikidata_results = []

    if wikidata_results:
        best_entity, best_score = _pick_best_wikidata(wikidata_results, parsed.inferred_jurisdiction)
        if best_entity:
            existing = await _db_lookup_by_qid(pool, best_entity.qid)
            if existing:
                company_id = str(existing.get("company_id", ""))
                has_data = await _db_has_emissions(pool, company_id)
                is_new = False
            else:
                fields = _entity_to_company_fields(best_entity)
                company_id = await _db_upsert_company(pool, fields)
                has_data = False
                is_new = True

            await _db_log_match(pool, parsed.original_input, name,
                [{"qid": e.qid, "label": e.label, "country": e.country_code, "source": "wikidata"} for e in wikidata_results],
                company_id, "wikidata")
            return MatchResult(company_id=company_id, canonical_name=best_entity.label or name,
                is_new=is_new, source="wikidata", match_score=best_score,
                wikidata_qid=best_entity.qid, has_existing_data=has_data)

    # Step 3: No match — create bare-bones company
    logger.warning("No match found for %r in local DB or Wikidata", name)
    fields = {
        "canonical_name": name,
        "legal_name": parsed.original_input if parsed.legal_suffix else None,
        "aliases": [parsed.original_input] if parsed.original_input != name else [],
        "hq_country": parsed.inferred_jurisdiction,
        "is_public": False,
    }
    company_id = await _db_upsert_company(pool, fields)
    await _db_log_match(pool, parsed.original_input, name, [], company_id, "local_db")
    return MatchResult(company_id=company_id, canonical_name=name, is_new=True,
        source="local_db", match_score=0.0, wikidata_qid=None)
