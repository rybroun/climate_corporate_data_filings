"""
Pipeline Step 1 — Input Parsing & Normalization.

Takes raw user input (company name, Wikidata QID, or URL) and produces a
structured ParsedQuery with normalized name, legal suffix, and inferred
jurisdiction.

Primary path: Claude API with tool use for structured output.
Fallback: regex-based parser when ANTHROPIC_API_KEY is not set.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ParsedQuery:
    normalized_name: str
    legal_suffix: str | None
    inferred_jurisdiction: str | None  # ISO alpha-2
    original_input: str
    input_type: str  # "company_name" | "wikidata_qid" | "url"
    confidence: float


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Common legal suffixes and their typical jurisdictions
_SUFFIX_JURISDICTION: dict[str, str] = {
    "S.A.": "FR",
    "SA": "FR",
    "Inc.": "US",
    "Inc": "US",
    "Corp.": "US",
    "Corp": "US",
    "Corporation": "US",
    "LLC": "US",
    "Ltd.": "GB",
    "Ltd": "GB",
    "Limited": "GB",
    "PLC": "GB",
    "Plc": "GB",
    "plc": "GB",
    "GmbH": "DE",
    "AG": "DE",
    "SE": "DE",
    "KG": "DE",
    "KGaA": "DE",
    "S.p.A.": "IT",
    "SpA": "IT",
    "S.r.l.": "IT",
    "Srl": "IT",
    "S.L.": "ES",
    "SL": "ES",
    "B.V.": "NL",
    "BV": "NL",
    "N.V.": "NL",
    "NV": "NL",
    "A/S": "DK",
    "AS": "NO",
    "ASA": "NO",
    "AB": "SE",
    "Oy": "FI",
    "Oyj": "FI",
    "Pty Ltd": "AU",
    "Pty Ltd.": "AU",
    "Ltda.": "BR",
    "Ltda": "BR",
    "S.A.B. de C.V.": "MX",
    "S.A. de C.V.": "MX",
    "K.K.": "JP",
    "Co., Ltd.": "JP",
    "Co. Ltd.": "JP",
    "SARL": "FR",
    "SAS": "FR",
    "S.A.S.": "FR",
    "Bhd": "MY",
    "Berhad": "MY",
    "Pte Ltd": "SG",
    "Pte Ltd.": "SG",
    "Tbk": "ID",
}

# Build a regex pattern that matches any suffix (longest first to avoid partial matches)
_SUFFIXES_SORTED = sorted(_SUFFIX_JURISDICTION.keys(), key=len, reverse=True)
_SUFFIX_PATTERN = re.compile(
    r"\s+(" + "|".join(re.escape(s) for s in _SUFFIXES_SORTED) + r")\.?\s*$",
    re.IGNORECASE,
)

# Wikidata QID pattern
_QID_PATTERN = re.compile(r"^Q\d+$", re.IGNORECASE)

# URL pattern (loose)
_URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Claude API tool definition for structured output
# ---------------------------------------------------------------------------

_PARSE_TOOL = {
    "name": "parsed_company_query",
    "description": (
        "Output the normalized company name, legal suffix, and inferred "
        "jurisdiction from the raw user input."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "normalized_name": {
                "type": "string",
                "description": (
                    "The company name without legal suffixes, parenthetical "
                    "notes, or country qualifiers. Just the core trading name."
                ),
            },
            "legal_suffix": {
                "type": ["string", "null"],
                "description": (
                    "The legal suffix if present (e.g. 'S.A.', 'Inc.', 'GmbH', "
                    "'PLC', 'Ltd.'). null if none detected."
                ),
            },
            "inferred_jurisdiction": {
                "type": ["string", "null"],
                "description": (
                    "ISO 3166-1 alpha-2 country code inferred from the legal "
                    "suffix or other context clues. null if uncertain."
                ),
            },
            "confidence": {
                "type": "number",
                "description": "Confidence in the normalization (0.0 to 1.0).",
            },
        },
        "required": ["normalized_name", "legal_suffix", "inferred_jurisdiction", "confidence"],
    },
}

_SYSTEM_PROMPT = (
    "You are a company name normalizer. Given a raw user input, extract:\n"
    "- The normalized company name (without legal suffixes like S.A., Inc., "
    "Ltd., GmbH, PLC, etc.)\n"
    "- The legal suffix if present\n"
    "- The inferred jurisdiction based on the suffix (ISO 3166-1 alpha-2)\n\n"
    "Use the parsed_company_query tool to return your structured output. "
    "Always call the tool exactly once."
)


# ---------------------------------------------------------------------------
# Regex-based fallback parser
# ---------------------------------------------------------------------------

def _parse_regex(raw_input: str) -> ParsedQuery:
    """Simple regex-based parser for when the Claude API is unavailable."""
    text = raw_input.strip()

    match = _SUFFIX_PATTERN.search(text)
    if match:
        suffix = match.group(1)
        normalized = text[: match.start()].strip()
        # Look up jurisdiction (case-insensitive match)
        jurisdiction = None
        for known_suffix, country in _SUFFIX_JURISDICTION.items():
            if known_suffix.lower() == suffix.lower():
                jurisdiction = country
                break
        return ParsedQuery(
            normalized_name=normalized,
            legal_suffix=suffix,
            inferred_jurisdiction=jurisdiction,
            original_input=raw_input,
            input_type="company_name",
            confidence=0.75,
        )

    # No suffix detected
    return ParsedQuery(
        normalized_name=text,
        legal_suffix=None,
        inferred_jurisdiction=None,
        original_input=raw_input,
        input_type="company_name",
        confidence=0.60,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def parse_query(raw_input: str) -> ParsedQuery:
    """Parse and normalize a raw user input into a structured query.

    Handles three input types:
    - Wikidata QID (``Q12345``) — returned immediately, no LLM call.
    - URL (``https://...``) — tagged as URL, name extracted.
    - Company name — normalized via Claude API (or regex fallback).

    Parameters
    ----------
    raw_input:
        The raw string from the user's search bar.

    Returns
    -------
    ParsedQuery with normalized fields.
    """
    text = raw_input.strip()

    if not text:
        return ParsedQuery(
            normalized_name="",
            legal_suffix=None,
            inferred_jurisdiction=None,
            original_input=raw_input,
            input_type="company_name",
            confidence=0.0,
        )

    # --- Fast path: Wikidata QID ---
    if _QID_PATTERN.match(text):
        return ParsedQuery(
            normalized_name=text.upper(),
            legal_suffix=None,
            inferred_jurisdiction=None,
            original_input=raw_input,
            input_type="wikidata_qid",
            confidence=1.0,
        )

    # --- URL input ---
    if _URL_PATTERN.match(text):
        return ParsedQuery(
            normalized_name=text,
            legal_suffix=None,
            inferred_jurisdiction=None,
            original_input=raw_input,
            input_type="url",
            confidence=0.5,
        )

    # --- Company name: try Claude API, fall back to regex ---
    if not settings.anthropic_api_key:
        logger.info("ANTHROPIC_API_KEY not set; using regex fallback for parsing")
        return _parse_regex(text)

    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            system=_SYSTEM_PROMPT,
            tools=[_PARSE_TOOL],
            messages=[
                {"role": "user", "content": text},
            ],
        )

        # Extract tool use result
        for block in response.content:
            if block.type == "tool_use" and block.name == "parsed_company_query":
                tool_input = block.input
                return ParsedQuery(
                    normalized_name=tool_input.get("normalized_name", text),
                    legal_suffix=tool_input.get("legal_suffix"),
                    inferred_jurisdiction=tool_input.get("inferred_jurisdiction"),
                    original_input=raw_input,
                    input_type="company_name",
                    confidence=float(tool_input.get("confidence", 0.9)),
                )

        # Tool was not called — fall back to regex
        logger.warning("Claude did not call the parse tool; falling back to regex")
        return _parse_regex(text)

    except Exception:
        logger.warning("Claude API call failed; falling back to regex parser", exc_info=True)
        return _parse_regex(text)
