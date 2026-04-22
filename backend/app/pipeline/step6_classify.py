"""
Step 6: Category mapping via Claude.

Maps company-native emission categories to GHG Protocol standard codes.
Handles split allocations (e.g., "Logistics" -> 50% s3_4 + 50% s3_9).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from app.config import settings
from app.services.claude_extractor import LineItemExtraction

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GHG Protocol reference table for Claude context
# ---------------------------------------------------------------------------

_GHG_REFERENCE = """
GHG Protocol Categories:
- s1: Scope 1 - Direct emissions (fuel combustion, fleet, process)
- s2_loc: Scope 2 Location-based - Purchased electricity (grid average)
- s2_mkt: Scope 2 Market-based - Purchased electricity (contractual)
- s3_1: Cat 1 - Purchased Goods & Services
- s3_2: Cat 2 - Capital Goods
- s3_3: Cat 3 - Fuel- and Energy-Related Activities (not in Scope 1/2)
- s3_4: Cat 4 - Upstream Transportation & Distribution
- s3_5: Cat 5 - Waste Generated in Operations
- s3_6: Cat 6 - Business Travel
- s3_7: Cat 7 - Employee Commuting
- s3_8: Cat 8 - Upstream Leased Assets
- s3_9: Cat 9 - Downstream Transportation & Distribution
- s3_10: Cat 10 - Processing of Sold Products
- s3_11: Cat 11 - Use of Sold Products
- s3_12: Cat 12 - End-of-Life Treatment of Sold Products
- s3_13: Cat 13 - Downstream Leased Assets
- s3_14: Cat 14 - Franchises
- s3_15: Cat 15 - Investments
"""

_CLASSIFY_TOOL = {
    "name": "record_mappings",
    "description": "Record GHG Protocol category mappings for native emission categories.",
    "input_schema": {
        "type": "object",
        "properties": {
            "mappings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "native_category": {"type": "string"},
                        "ghg_code": {"type": "string"},
                        "allocation_pct": {
                            "type": "number",
                            "description": "Fraction 0.0 to 1.0 allocated to this GHG code",
                        },
                        "rationale": {"type": "string"},
                    },
                    "required": ["native_category", "ghg_code", "allocation_pct", "rationale"],
                },
            },
        },
        "required": ["mappings"],
    },
}

# ---------------------------------------------------------------------------
# Heuristic fallback mapping
# ---------------------------------------------------------------------------

_HEURISTIC_MAP: dict[str, list[tuple[str, float, str]]] = {
    # (ghg_code, allocation_pct, rationale)
    "milk": [("s3_1", 1.0, "Dairy ingredients are purchased goods (Cat 1)")],
    "dairy ingredients": [("s3_1", 1.0, "Dairy ingredients are purchased goods (Cat 1)")],
    "non-dairy": [("s3_1", 1.0, "Non-dairy ingredients are purchased goods (Cat 1)")],
    "packaging": [("s3_1", 1.0, "Packaging materials are purchased goods (Cat 1)")],
    "logistics": [
        ("s3_4", 0.5, "Upstream portion of logistics (Cat 4)"),
        ("s3_9", 0.5, "Downstream portion of logistics (Cat 9)"),
    ],
    "co-manufacturing": [("s3_1", 1.0, "Contract manufacturing is purchased goods (Cat 1)")],
    "energy": [("s3_3", 1.0, "Fuel- and energy-related activities (Cat 3)")],
    "energy & industrial": [("s3_3", 1.0, "Fuel- and energy-related activities (Cat 3)")],
    "waste": [("s3_5", 1.0, "Waste generated in operations (Cat 5)")],
    "business travel": [("s3_6", 1.0, "Business travel (Cat 6)")],
    "employee commuting": [("s3_7", 1.0, "Employee commuting (Cat 7)")],
    "capital goods": [("s3_2", 1.0, "Capital goods (Cat 2)")],
    "investments": [("s3_15", 1.0, "Investments (Cat 15)")],
    "franchises": [("s3_14", 1.0, "Franchises (Cat 14)")],
    "use of sold products": [("s3_11", 1.0, "Use of sold products (Cat 11)")],
    "end-of-life": [("s3_12", 1.0, "End-of-life treatment (Cat 12)")],
    "purchased goods": [("s3_1", 1.0, "Purchased goods and services (Cat 1)")],
    "purchased goods and services": [("s3_1", 1.0, "Purchased goods and services (Cat 1)")],
}


def _heuristic_classify(native_category: str) -> list[tuple[str, float, str]]:
    """Apply simple keyword-based GHG Protocol mapping."""
    key = native_category.lower().strip()

    # Exact match
    if key in _HEURISTIC_MAP:
        return _HEURISTIC_MAP[key]

    # Partial match
    for pattern, mappings in _HEURISTIC_MAP.items():
        if pattern in key:
            return mappings

    # Default: assume Scope 3 Cat 1 (purchased goods)
    return [("s3_1", 1.0, f"Default mapping for unrecognized category '{native_category}'")]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def classify_categories(
    line_items: list[LineItemExtraction],
    company_id: str,
    pool,
) -> list[dict]:
    """Map company-native emission categories to GHG Protocol codes.

    Collects unique native categories, calls Claude API (or falls back to
    heuristic mapping), and inserts COMPANY_CATEGORY_MAPPING rows.

    Parameters
    ----------
    line_items:
        Extracted line items with native_category values.
    company_id:
        Internal company UUID.
    pool:
        asyncpg connection pool (or None for mock mode).

    Returns
    -------
    List of mapping dicts with keys: mapping_id, company_id, native_category,
    ghg_code, allocation_pct, rationale.
    """
    # Collect unique native categories
    unique_categories = list({item.native_category for item in line_items})

    if not unique_categories:
        logger.info("No line items to classify")
        return []

    logger.info("Classifying %d unique native categories", len(unique_categories))

    mappings: list[dict] = []

    if settings.anthropic_api_key:
        # Use Claude for classification
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

        categories_text = "\n".join(f"- {cat}" for cat in unique_categories)
        user_content = (
            f"Map these company-native emission categories to GHG Protocol codes.\n\n"
            f"Native categories:\n{categories_text}\n\n"
            f"Reference:\n{_GHG_REFERENCE}\n\n"
            "For each native category, provide one or more GHG code mappings with "
            "allocation percentages (must sum to 1.0 for each native category). "
            "For example, 'Logistics' might split 50/50 between s3_4 and s3_9. "
            "Provide a brief rationale for each mapping."
        )

        try:
            response = await client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                temperature=0,
                system=(
                    "You are a GHG Protocol expert. Map company-native emission categories "
                    "to standard GHG Protocol scope/category codes. Be precise about split "
                    "allocations. Use the record_mappings tool."
                ),
                messages=[{"role": "user", "content": user_content}],
                tools=[_CLASSIFY_TOOL],
            )

            for block in response.content:
                if block.type == "tool_use":
                    raw_mappings = block.input.get("mappings", [])
                    for m in raw_mappings:
                        mappings.append({
                            "mapping_id": str(uuid.uuid4()),
                            "company_id": company_id,
                            "native_category": m["native_category"],
                            "ghg_code": m["ghg_code"],
                            "allocation_pct": m["allocation_pct"],
                            "rationale": m["rationale"],
                        })
                    break

        except Exception as e:
            logger.warning("Claude category classification failed: %s, using heuristic", e)
            mappings = []

    # Fallback to heuristic if Claude didn't produce results
    if not mappings:
        logger.info("Using heuristic category mapping")
        for cat in unique_categories:
            heuristic_results = _heuristic_classify(cat)
            for ghg_code, alloc_pct, rationale in heuristic_results:
                mappings.append({
                    "mapping_id": str(uuid.uuid4()),
                    "company_id": company_id,
                    "native_category": cat,
                    "ghg_code": ghg_code,
                    "allocation_pct": alloc_pct,
                    "rationale": rationale,
                })

    # Write to DB
    if pool is not None:
        for m in mappings:
            try:
                await pool.execute(
                    """
                    INSERT INTO company_category_mapping (
                        mapping_id, company_id, native_category,
                        ghg_code, allocation_pct, rationale,
                        created_at, updated_at
                    ) VALUES (
                        $1::uuid, $2::uuid, $3, $4, $5, $6, NOW(), NOW()
                    )
                    ON CONFLICT (company_id, native_category, ghg_code, effective_from_year)
                    DO UPDATE SET
                        allocation_pct = EXCLUDED.allocation_pct,
                        rationale = EXCLUDED.rationale,
                        updated_at = NOW()
                    """,
                    m["mapping_id"],
                    m["company_id"],
                    m["native_category"],
                    m["ghg_code"],
                    m["allocation_pct"],
                    m["rationale"],
                )
            except Exception as e:
                logger.warning(
                    "Failed to insert category mapping %s -> %s: %s",
                    m["native_category"],
                    m["ghg_code"],
                    e,
                )

    logger.info(
        "Step 6 complete: %d category mappings for %d native categories",
        len(mappings),
        len(unique_categories),
    )

    return mappings
