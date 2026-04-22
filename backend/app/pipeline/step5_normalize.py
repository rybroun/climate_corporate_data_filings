"""
Step 5: Unit normalization.

Converts emissions values from various units to tCO2e (metric tons CO2 equivalent).
"""

from __future__ import annotations

import logging
import re

from app.services.claude_extractor import EmissionsExtraction, LineItemExtraction

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Unit conversion factors to tCO2e
# ---------------------------------------------------------------------------

_UNIT_FACTORS: dict[str, float] = {
    "tco2e": 1.0,
    "tco2": 1.0,
    "t co2e": 1.0,
    "t co2": 1.0,
    "tonnes co2e": 1.0,
    "metric tons co2e": 1.0,
    "ktco2e": 1_000.0,
    "ktco2": 1_000.0,
    "kt co2e": 1_000.0,
    "kt co2": 1_000.0,
    "kilo tonnes co2e": 1_000.0,
    "thousand tonnes co2e": 1_000.0,
    "mtco2e": 1_000_000.0,
    "mtco2": 1_000_000.0,
    "mt co2e": 1_000_000.0,
    "mt co2": 1_000_000.0,
    "million tonnes co2e": 1_000_000.0,
    "gtco2e": 1_000_000_000.0,
    "gtco2": 1_000_000_000.0,
    "gt co2e": 1_000_000_000.0,
    "gt co2": 1_000_000_000.0,
    "kgco2e": 0.001,
    "kgco2": 0.001,
    "kg co2e": 0.001,
    "kg co2": 0.001,
}


def normalize_emissions(value: float, unit: str) -> float:
    """Convert an emissions value from the given unit to tCO2e.

    Parameters
    ----------
    value:
        The numeric emissions value.
    unit:
        The unit string (e.g., "ktCO2e", "MtCO2", "kgCO2e").
        Case-insensitive. If empty or unrecognized, assumes tCO2e.

    Returns
    -------
    Value in tCO2e.
    """
    if not unit:
        return value

    normalized_unit = unit.strip().lower()

    factor = _UNIT_FACTORS.get(normalized_unit)

    if factor is None:
        # Try partial matching for common patterns
        if re.search(r"^gt", normalized_unit):
            factor = 1_000_000_000.0
        elif re.search(r"^mt", normalized_unit):
            factor = 1_000_000.0
        elif re.search(r"^kt", normalized_unit):
            factor = 1_000.0
        elif re.search(r"^kg", normalized_unit):
            factor = 0.001
        else:
            logger.warning("Unrecognized unit '%s', assuming tCO2e", unit)
            factor = 1.0

    if factor != 1.0:
        logger.info(
            "Converting %.2f %s -> %.2f tCO2e (factor: %g)",
            value,
            unit,
            value * factor,
            factor,
        )

    return value * factor


def normalize_extraction(extraction: EmissionsExtraction) -> EmissionsExtraction:
    """Apply unit normalization to all emission values in an extraction.

    Currently, the Claude extractor is prompted to return values in tCO2e.
    This function applies sanity checks and logs any conversions.

    The function checks if values seem to be in the wrong scale (e.g.,
    Scope 1 emissions of 564 might be in ktCO2e rather than tCO2e for
    a large company) but does NOT auto-correct without a unit signal --
    it only logs warnings.

    Parameters
    ----------
    extraction:
        The raw EmissionsExtraction from the Claude extractor.

    Returns
    -------
    A new EmissionsExtraction with normalized values.
    """
    conversions_made = 0

    # Copy scalar values (they should already be in tCO2e from Claude)
    scope_1 = extraction.scope_1_tco2e
    scope_2_loc = extraction.scope_2_location_tco2e
    scope_2_mkt = extraction.scope_2_market_tco2e
    scope_3 = extraction.scope_3_total_tco2e

    # Sanity checks: flag suspiciously small or large values
    for label, val in [
        ("Scope 1", scope_1),
        ("Scope 2 (location)", scope_2_loc),
        ("Scope 2 (market)", scope_2_mkt),
        ("Scope 3", scope_3),
    ]:
        if val is not None:
            if val < 0:
                logger.warning("%s is negative (%.2f) -- possible extraction error", label, val)
            elif val > 1e12:
                logger.warning(
                    "%s is extremely large (%.2f) -- may be in wrong unit", label, val
                )

    # Normalize line items
    normalized_items: list[LineItemExtraction] = []
    for item in extraction.line_items:
        normalized_value = item.tco2e  # Already in tCO2e from prompt

        # Sanity check
        if normalized_value < 0:
            logger.warning(
                "Line item '%s' has negative value (%.2f)",
                item.native_category,
                normalized_value,
            )

        normalized_items.append(
            LineItemExtraction(
                native_category=item.native_category,
                tco2e=normalized_value,
                data_quality_tier=item.data_quality_tier,
                tags=item.tags,
            )
        )

    result = EmissionsExtraction(
        reporting_year=extraction.reporting_year,
        scope_1_tco2e=scope_1,
        scope_2_location_tco2e=scope_2_loc,
        scope_2_market_tco2e=scope_2_mkt,
        scope_3_total_tco2e=scope_3,
        methodology=extraction.methodology,
        verification_status=extraction.verification_status,
        verifier_name=extraction.verifier_name,
        boundary_definition=extraction.boundary_definition,
        page_number=extraction.page_number,
        section_reference=extraction.section_reference,
        confidence=extraction.confidence,
        line_items=normalized_items,
    )

    logger.info(
        "Step 5 normalization complete: %d conversions applied, %d line items checked",
        conversions_made,
        len(normalized_items),
    )

    return result
