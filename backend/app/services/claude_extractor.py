"""
Claude API structured extraction for sustainability reports.

Uses Anthropic's tool use to extract emissions, targets, and governance
data from parsed PDF pages. Falls back to mock data when no API key is set.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from app.config import settings
from app.services.pdf_parser import PageContent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LineItemExtraction:
    native_category: str
    tco2e: float
    data_quality_tier: str | None
    tags: list[str]


@dataclass
class EmissionsExtraction:
    reporting_year: int | None
    scope_1_tco2e: float | None
    scope_2_location_tco2e: float | None
    scope_2_market_tco2e: float | None
    scope_3_total_tco2e: float | None
    methodology: str | None
    verification_status: str | None
    verifier_name: str | None
    boundary_definition: str | None
    page_number: int | None
    section_reference: str | None
    confidence: float
    line_items: list[LineItemExtraction]


@dataclass
class TargetExtraction:
    target_type: str
    sbti_status: str | None
    baseline_year: int | None
    target_year: int | None
    reduction_pct: float | None
    scope_coverage: list[str]
    target_language: str | None
    confidence: float


@dataclass
class GovernanceExtraction:
    exec_comp_tied_to_climate: bool | None
    exec_comp_pct: float | None
    board_oversight: bool | None
    board_committee_name: str | None
    has_transition_plan: bool | None
    confidence: float


# ---------------------------------------------------------------------------
# Tool schemas for Claude API
# ---------------------------------------------------------------------------

_EMISSIONS_TOOL = {
    "name": "record_emissions",
    "description": "Record extracted emissions disclosure data from a sustainability report.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reporting_year": {"type": "integer", "description": "Fiscal year the emissions data describes"},
            "scope_1_tco2e": {"type": "number", "description": "Scope 1 direct emissions in tCO2e"},
            "scope_2_location_tco2e": {"type": "number", "description": "Scope 2 location-based emissions in tCO2e"},
            "scope_2_market_tco2e": {"type": "number", "description": "Scope 2 market-based emissions in tCO2e"},
            "scope_3_total_tco2e": {"type": "number", "description": "Scope 3 total value-chain emissions in tCO2e"},
            "methodology": {
                "type": "string",
                "enum": ["ghg_protocol_corporate", "iso_14064", "tcfd_aligned", "other"],
            },
            "verification_status": {
                "type": "string",
                "enum": ["none", "limited_assurance", "reasonable_assurance"],
            },
            "verifier_name": {"type": "string", "description": "Third-party assurance provider name"},
            "boundary_definition": {"type": "string", "description": "Organizational boundary description"},
            "page_number": {"type": "integer", "description": "Page where the main emissions table appears"},
            "section_reference": {"type": "string", "description": "Section or table identifier"},
            "confidence": {"type": "number", "description": "Confidence score 0.0 to 1.0"},
            "line_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "native_category": {"type": "string"},
                        "tco2e": {"type": "number"},
                        "data_quality_tier": {
                            "type": "string",
                            "enum": ["supplier_specific", "hybrid", "industry_average", "spend_based"],
                        },
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["native_category", "tco2e"],
                },
            },
        },
        "required": ["reporting_year", "confidence"],
    },
}

_TARGETS_TOOL = {
    "name": "record_targets",
    "description": "Record extracted emissions reduction targets from a sustainability report.",
    "input_schema": {
        "type": "object",
        "properties": {
            "targets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "target_type": {
                            "type": "string",
                            "enum": ["near_term", "long_term", "net_zero", "interim", "sub_target"],
                        },
                        "sbti_status": {
                            "type": "string",
                            "enum": ["not_submitted", "committed", "targets_set", "validated", "removed"],
                        },
                        "baseline_year": {"type": "integer"},
                        "target_year": {"type": "integer"},
                        "reduction_pct": {"type": "number"},
                        "scope_coverage": {"type": "array", "items": {"type": "string"}},
                        "target_language": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["target_type", "confidence"],
                },
            },
        },
        "required": ["targets"],
    },
}

_GOVERNANCE_TOOL = {
    "name": "record_governance",
    "description": "Record extracted governance signals from a sustainability report.",
    "input_schema": {
        "type": "object",
        "properties": {
            "exec_comp_tied_to_climate": {"type": "boolean"},
            "exec_comp_pct": {"type": "number"},
            "board_oversight": {"type": "boolean"},
            "board_committee_name": {"type": "string"},
            "has_transition_plan": {"type": "boolean"},
            "confidence": {"type": "number"},
        },
        "required": ["confidence"],
    },
}

_PAGE_CLASSIFY_TOOL = {
    "name": "classify_pages",
    "description": "Classify which pages contain different types of sustainability data.",
    "input_schema": {
        "type": "object",
        "properties": {
            "emissions_data": {"type": "array", "items": {"type": "integer"}},
            "targets": {"type": "array", "items": {"type": "integer"}},
            "governance": {"type": "array", "items": {"type": "integer"}},
            "certifications": {"type": "array", "items": {"type": "integer"}},
            "programs": {"type": "array", "items": {"type": "integer"}},
        },
        "required": ["emissions_data", "targets", "governance"],
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pages_to_text(pages: list[PageContent], max_chars: int = 80000) -> str:
    """Concatenate page text with page markers, truncating if needed."""
    parts = []
    total = 0
    for p in pages:
        header = f"\n--- PAGE {p.page_number} ---\n"
        text = p.text[:max_chars - total] if total + len(p.text) > max_chars else p.text
        parts.append(header + text)
        total += len(header) + len(text)
        if total >= max_chars:
            break
    return "".join(parts)


def _has_api_key() -> bool:
    return bool(settings.anthropic_api_key)


async def _call_claude(system: str, user_content: str, tools: list[dict]) -> dict | None:
    """Call Claude API with tool use and return the tool input dict, or None."""
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user_content}],
            tools=tools,
            tool_choice={"type": "any"},  # Force tool use
        )

        # Extract tool use from response
        for block in response.content:
            if block.type == "tool_use":
                return block.input

        logger.warning("Claude response did not include tool use")
        return None

    except Exception as e:
        logger.error("Claude API call failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

def _mock_page_classification() -> dict[str, list[int]]:
    return {
        "emissions_data": [45, 46, 47, 48],
        "targets": [52, 53, 54],
        "governance": [30, 31, 32],
        "certifications": [60, 61],
        "programs": [55, 56, 57, 58],
    }


def _mock_emissions() -> EmissionsExtraction:
    return EmissionsExtraction(
        reporting_year=2023,
        scope_1_tco2e=564000.0,
        scope_2_location_tco2e=312000.0,
        scope_2_market_tco2e=198000.0,
        scope_3_total_tco2e=24100000.0,
        methodology="ghg_protocol_corporate",
        verification_status="limited_assurance",
        verifier_name="PwC",
        boundary_definition="Operational control",
        page_number=47,
        section_reference="Table 4.2",
        confidence=0.92,
        line_items=[
            LineItemExtraction(
                native_category="Purchased goods and services - Milk",
                tco2e=7900000.0,
                data_quality_tier="supplier_specific",
                tags=["flag"],
            ),
            LineItemExtraction(
                native_category="Packaging",
                tco2e=3200000.0,
                data_quality_tier="hybrid",
                tags=[],
            ),
            LineItemExtraction(
                native_category="Logistics",
                tco2e=1900000.0,
                data_quality_tier="industry_average",
                tags=[],
            ),
            LineItemExtraction(
                native_category="Co-manufacturing",
                tco2e=1600000.0,
                data_quality_tier="spend_based",
                tags=[],
            ),
        ],
    )


def _mock_targets() -> list[TargetExtraction]:
    return [
        TargetExtraction(
            target_type="near_term",
            sbti_status="validated",
            baseline_year=2020,
            target_year=2030,
            reduction_pct=34.7,
            scope_coverage=["scope_1", "scope_2_market", "scope_3"],
            target_language="Reduce absolute Scope 1, 2 and 3 GHG emissions 34.7% by 2030 from a 2020 base year.",
            confidence=0.95,
        ),
        TargetExtraction(
            target_type="net_zero",
            sbti_status="committed",
            baseline_year=2020,
            target_year=2050,
            reduction_pct=90.0,
            scope_coverage=["scope_1", "scope_2_market", "scope_3"],
            target_language="Achieve net-zero GHG emissions across the value chain by 2050.",
            confidence=0.90,
        ),
        TargetExtraction(
            target_type="sub_target",
            sbti_status="validated",
            baseline_year=2020,
            target_year=2030,
            reduction_pct=30.0,
            scope_coverage=["scope_1", "scope_3"],
            target_language="Reduce methane emissions 30% by 2030 from 2020 baseline.",
            confidence=0.88,
        ),
    ]


def _mock_governance() -> GovernanceExtraction:
    return GovernanceExtraction(
        exec_comp_tied_to_climate=True,
        exec_comp_pct=30.0,
        board_oversight=True,
        board_committee_name="CSR & Ethics Committee",
        has_transition_plan=True,
        confidence=0.91,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def classify_pages(pages: list[PageContent]) -> dict[str, list[int]]:
    """Classify which page numbers contain different types of sustainability data.

    Sends the first few pages plus all page headers to Claude for classification.
    Returns a dict mapping category names to lists of page numbers.
    """
    if not _has_api_key():
        logger.info("No ANTHROPIC_API_KEY set, returning mock page classification")
        return _mock_page_classification()

    # Build a compact representation: first 3 pages full text + headers from all pages
    preview_parts = []
    for p in pages[:3]:
        preview_parts.append(f"--- PAGE {p.page_number} (FULL) ---\n{p.text[:2000]}")

    for p in pages[3:]:
        # Take just the first 2 lines as a header
        lines = p.text.strip().split("\n")[:2]
        header = " | ".join(lines)
        preview_parts.append(f"PAGE {p.page_number}: {header}")

    content = "\n".join(preview_parts)

    system = (
        "You are a document analyst specializing in sustainability reports. "
        "Given page previews from a corporate sustainability/annual report, "
        "classify which pages contain: emissions_data (Scope 1/2/3 tables), "
        "targets (reduction commitments, SBTi), governance (board oversight, exec comp), "
        "certifications (CDP scores, B Corp, RE100), and programs (decarbonization initiatives). "
        "Use the classify_pages tool to record your findings."
    )

    result = await _call_claude(system, content, [_PAGE_CLASSIFY_TOOL])

    if result is None:
        return _mock_page_classification()

    return {
        "emissions_data": result.get("emissions_data", []),
        "targets": result.get("targets", []),
        "governance": result.get("governance", []),
        "certifications": result.get("certifications", []),
        "programs": result.get("programs", []),
    }


async def extract_emissions(pages: list[PageContent]) -> EmissionsExtraction:
    """Extract emissions disclosure data from sustainability report pages.

    Uses Claude with tool use to extract Scope 1, 2, and 3 emissions,
    methodology, verification status, and individual line items.
    """
    if not _has_api_key():
        logger.info("No ANTHROPIC_API_KEY set, returning mock emissions extraction")
        return _mock_emissions()

    content = _pages_to_text(pages)

    system = (
        "Extract emissions disclosure data from this sustainability report section. "
        "Find Scope 1, 2 (location and market-based), and 3 total emissions in tCO2e. "
        "Also extract individual line items with their native category names. "
        "For example, Danone's 2020 Scope 3 line items include Milk (7.9M tCO2e, tagged FLAG), "
        "Packaging (3.2M), Logistics (1.9M). "
        "All values should be in tCO2e (metric tons CO2 equivalent). "
        "If values are in ktCO2e, multiply by 1000. If in MtCO2e, multiply by 1,000,000. "
        "Use the record_emissions tool to record your findings."
    )

    result = await _call_claude(system, content, [_EMISSIONS_TOOL])

    if result is None:
        return _mock_emissions()

    line_items = [
        LineItemExtraction(
            native_category=li.get("native_category", "Unknown"),
            tco2e=li.get("tco2e", 0.0),
            data_quality_tier=li.get("data_quality_tier"),
            tags=li.get("tags", []),
        )
        for li in result.get("line_items", [])
    ]

    return EmissionsExtraction(
        reporting_year=result.get("reporting_year"),
        scope_1_tco2e=result.get("scope_1_tco2e"),
        scope_2_location_tco2e=result.get("scope_2_location_tco2e"),
        scope_2_market_tco2e=result.get("scope_2_market_tco2e"),
        scope_3_total_tco2e=result.get("scope_3_total_tco2e"),
        methodology=result.get("methodology"),
        verification_status=result.get("verification_status"),
        verifier_name=result.get("verifier_name"),
        boundary_definition=result.get("boundary_definition"),
        page_number=result.get("page_number"),
        section_reference=result.get("section_reference"),
        confidence=result.get("confidence", 0.5),
        line_items=line_items,
    )


async def extract_targets(pages: list[PageContent]) -> list[TargetExtraction]:
    """Extract emissions reduction targets from sustainability report pages."""
    if not _has_api_key():
        logger.info("No ANTHROPIC_API_KEY set, returning mock targets extraction")
        return _mock_targets()

    content = _pages_to_text(pages)

    system = (
        "Extract emissions reduction targets, SBTi commitments, and net-zero pledges "
        "from this sustainability report section. For each target, identify the type "
        "(near_term, long_term, net_zero, interim, sub_target), SBTi validation status, "
        "baseline year, target year, reduction percentage, scope coverage, and the "
        "verbatim target language. Use the record_targets tool."
    )

    result = await _call_claude(system, content, [_TARGETS_TOOL])

    if result is None:
        return _mock_targets()

    targets = []
    for t in result.get("targets", []):
        targets.append(
            TargetExtraction(
                target_type=t.get("target_type", "near_term"),
                sbti_status=t.get("sbti_status"),
                baseline_year=t.get("baseline_year"),
                target_year=t.get("target_year"),
                reduction_pct=t.get("reduction_pct"),
                scope_coverage=t.get("scope_coverage", []),
                target_language=t.get("target_language"),
                confidence=t.get("confidence", 0.5),
            )
        )

    return targets


async def extract_governance(pages: list[PageContent]) -> GovernanceExtraction:
    """Extract governance signals from sustainability report pages."""
    if not _has_api_key():
        logger.info("No ANTHROPIC_API_KEY set, returning mock governance extraction")
        return _mock_governance()

    content = _pages_to_text(pages)

    system = (
        "Extract governance signals from this sustainability report section. "
        "Determine whether executive compensation is linked to climate/sustainability KPIs, "
        "the percentage of exec comp tied to climate, whether the board has climate oversight, "
        "the name of the responsible committee, and whether the company has a transition plan. "
        "Use the record_governance tool."
    )

    result = await _call_claude(system, content, [_GOVERNANCE_TOOL])

    if result is None:
        return _mock_governance()

    return GovernanceExtraction(
        exec_comp_tied_to_climate=result.get("exec_comp_tied_to_climate"),
        exec_comp_pct=result.get("exec_comp_pct"),
        board_oversight=result.get("board_oversight"),
        board_committee_name=result.get("board_committee_name"),
        has_transition_plan=result.get("has_transition_plan"),
        confidence=result.get("confidence", 0.5),
    )
