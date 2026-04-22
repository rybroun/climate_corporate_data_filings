"""
Wikidata API client for entity resolution.

Uses the Wikidata REST API (wbsearchentities) and entity data endpoint
to look up companies by name or QID and extract structured identity fields.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class WikidataEntity:
    qid: str
    label: str
    description: str
    aliases: list[str]
    official_name: str | None
    country_code: str | None  # ISO alpha-2
    ticker: str | None
    stock_exchange: str | None
    lei: str | None
    website: str | None
    parent_org_qid: str | None
    industry: str | None
    inception: str | None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WIKIDATA_API = "https://www.wikidata.org/w/api.php"
_ENTITY_DATA_URL = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"

# QIDs representing company / business types (used to filter search results)
_COMPANY_TYPE_QIDS: set[str] = {
    "Q4830453",   # business
    "Q6881511",   # enterprise
    "Q783794",    # company
    "Q891723",    # public company
    "Q163740",    # nonprofit organization (some ESG-relevant)
    "Q43229",     # organization
    "Q4539101",   # publicly traded company
    "Q18127903",  # corporate group (Danone, Nestle, etc.)
    "Q1320047",   # private company
    "Q1762059",   # conglomerate
    "Q207652",    # multinational corporation
}

# Wikidata QID -> ISO alpha-2 mapping (countries AND major HQ cities)
# P159 (HQ location) returns cities, so we include them here too
_COUNTRY_QID_TO_ISO: dict[str, str] = {
    # Major HQ cities
    "Q90": "FR",     # Paris
    "Q84": "GB",     # London
    "Q60": "US",     # New York
    "Q65": "US",     # Los Angeles
    "Q1297": "US",   # Chicago
    "Q62": "US",     # San Francisco
    "Q1490": "JP",   # Tokyo
    "Q956": "CN",    # Beijing
    "Q8686": "CN",   # Shanghai
    "Q64": "DE",     # Berlin
    "Q1726": "DE",   # Munich
    "Q220": "IT",    # Rome
    "Q490": "IT",    # Milan
    "Q2807": "ES",   # Madrid
    "Q36600": "CH",  # Vevey (Nestlé HQ)
    "Q72": "CH",     # Zurich
    "Q727": "NL",    # Amsterdam
    "Q239": "BE",    # Brussels
    "Q1748": "DK",   # Copenhagen
    "Q1757": "FI",   # Helsinki
    "Q585": "NO",    # Oslo
    "Q1754": "SE",   # Stockholm
    "Q1761": "AT",   # Vienna
    "Q3616": "AU",   # Sydney
    "Q174": "BR",    # São Paulo
    "Q1489": "MX",   # Mexico City
    "Q1353": "IN",   # Delhi
    "Q1156": "IN",   # Mumbai
    "Q142": "FR",   # France
    "Q30": "US",    # United States
    "Q145": "GB",   # United Kingdom
    "Q39": "CH",    # Switzerland
    "Q183": "DE",   # Germany
    "Q38": "IT",    # Italy
    "Q29": "ES",    # Spain
    "Q31": "BE",    # Belgium
    "Q55": "NL",    # Netherlands
    "Q35": "DK",    # Denmark
    "Q20": "NO",    # Norway
    "Q34": "SE",    # Sweden
    "Q40": "AT",    # Austria
    "Q36": "PL",    # Poland
    "Q218": "RO",   # Romania
    "Q17": "JP",    # Japan
    "Q148": "CN",   # China
    "Q884": "KR",   # South Korea
    "Q668": "IN",   # India
    "Q155": "BR",   # Brazil
    "Q96": "MX",    # Mexico
    "Q408": "AU",   # Australia
    "Q16": "CA",    # Canada
    "Q28": "HU",    # Hungary
    "Q33": "FI",    # Finland
    "Q37": "LT",    # Lithuania
    "Q27": "IE",    # Ireland
    "Q32": "LU",    # Luxembourg
    "Q45": "PT",    # Portugal
    "Q41": "GR",    # Greece
    "Q213": "CZ",   # Czech Republic
    "Q214": "SK",   # Slovakia
    "Q191": "EE",   # Estonia
    "Q211": "LV",   # Latvia
    "Q215": "SI",   # Slovenia
    "Q219": "BG",   # Bulgaria
    "Q224": "HR",   # Croatia
    "Q229": "CY",   # Cyprus
    "Q233": "MT",   # Malta
    "Q252": "ID",   # Indonesia
    "Q334": "SG",   # Singapore
    "Q869": "TH",   # Thailand
    "Q928": "PH",   # Philippines
    "Q881": "VN",   # Vietnam
    "Q833": "MY",   # Malaysia
    "Q902": "BD",   # Bangladesh
    "Q159": "RU",   # Russia
    "Q212": "UA",   # Ukraine
    "Q794": "IR",   # Iran
    "Q843": "PK",   # Pakistan
    "Q79": "EG",    # Egypt
    "Q258": "ZA",   # South Africa
    "Q262": "DZ",   # Algeria
    "Q1028": "MA",  # Morocco
    "Q398": "BH",   # Bahrain
    "Q842": "OM",   # Oman
    "Q846": "QA",   # Qatar
    "Q851": "SA",   # Saudi Arabia
    "Q878": "AE",   # UAE
    "Q801": "IL",   # Israel
    "Q717": "VE",   # Venezuela
    "Q733": "PY",   # Paraguay
    "Q736": "EC",   # Ecuador
    "Q298": "CL",   # Chile
    "Q414": "AR",   # Argentina
    "Q419": "PE",   # Peru
    "Q739": "CO",   # Colombia
    "Q241": "CU",   # Cuba
    "Q800": "CR",   # Costa Rica
    "Q77": "UY",    # Uruguay
    "Q574": "TT",   # Trinidad and Tobago
    "Q664": "NZ",   # New Zealand
    "Q863": "TJ",   # Tajikistan
    "Q232": "KZ",   # Kazakhstan
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_claim_value(claims: dict, prop: str) -> Any | None:
    """Extract the first mainsnak value for a Wikidata property from claims."""
    prop_claims = claims.get(prop)
    if not prop_claims:
        return None

    snak = prop_claims[0].get("mainsnak", {})
    datavalue = snak.get("datavalue")
    if datavalue is None:
        return None

    val_type = datavalue.get("type")
    value = datavalue.get("value")

    if val_type == "wikibase-entityid":
        return value.get("id")
    if val_type == "string":
        return value
    if val_type == "monolingualtext":
        return value.get("text")
    if val_type == "time":
        # Return the ISO-ish date string, stripping leading +
        return value.get("time", "").lstrip("+")
    if val_type == "quantity":
        return value.get("amount")

    return None


def _get_entity_label(entity: dict, qid: str) -> str | None:
    """Resolve a QID to its English label from already-fetched entity data,
    or return the QID itself as fallback."""
    labels = entity.get("labels", {})
    en_label = labels.get("en", {})
    return en_label.get("value") if en_label else qid


def _is_company_entity(claims: dict) -> bool:
    """Check if entity looks like a company based on P31 (instance of),
    P414 (stock exchange), or P1278 (LEI)."""
    # Has stock exchange or LEI -> definitely a company
    if claims.get("P414") or claims.get("P1278"):
        return True

    # Check P31 (instance of)
    p31_claims = claims.get("P31", [])
    for claim in p31_claims:
        snak = claim.get("mainsnak", {})
        datavalue = snak.get("datavalue", {})
        value = datavalue.get("value", {})
        type_qid = value.get("id")
        if type_qid in _COMPANY_TYPE_QIDS:
            return True

    return False


def _parse_entity(qid: str, entity: dict) -> WikidataEntity:
    """Parse a raw Wikidata entity JSON object into a WikidataEntity."""
    claims = entity.get("claims", {})

    # Label
    label = _get_entity_label(entity, qid)

    # Description
    descriptions = entity.get("descriptions", {})
    description = descriptions.get("en", {}).get("value", "")

    # Aliases
    alias_list = entity.get("aliases", {}).get("en", [])
    aliases = [a.get("value", "") for a in alias_list if a.get("value")]

    # P1448 official name
    official_name = _get_claim_value(claims, "P1448")

    # P159 HQ location -> country, falling back to P17 country
    # P159 is more reliable for multinationals (e.g., Danone HQ is Paris/France)
    hq_qid = _get_claim_value(claims, "P159")
    country_code = _COUNTRY_QID_TO_ISO.get(hq_qid) if hq_qid else None
    if not country_code:
        # Try all P17 values and prefer known major countries
        if "P17" in claims:
            for claim in claims["P17"]:
                try:
                    qid = claim["mainsnak"]["datavalue"]["value"]["id"]
                    code = _COUNTRY_QID_TO_ISO.get(qid)
                    if code:
                        country_code = code
                        break
                except (KeyError, TypeError):
                    continue

    # P414 stock exchange + P249 ticker
    stock_exchange_qid = _get_claim_value(claims, "P414")
    stock_exchange = stock_exchange_qid  # Will be a QID; caller can resolve later
    ticker = _get_claim_value(claims, "P249")

    # P1278 LEI
    lei = _get_claim_value(claims, "P1278")

    # P856 official website
    website = _get_claim_value(claims, "P856")

    # P749 parent organization (QID)
    parent_org_qid = _get_claim_value(claims, "P749")

    # P452 industry (resolve to label if possible)
    industry_qid = _get_claim_value(claims, "P452")
    # For now, store the QID; we could resolve the label in a follow-up call
    industry = industry_qid

    # P571 inception
    inception = _get_claim_value(claims, "P571")

    return WikidataEntity(
        qid=qid,
        label=label,
        description=description,
        aliases=aliases,
        official_name=official_name,
        country_code=country_code,
        ticker=ticker,
        stock_exchange=stock_exchange,
        lei=lei,
        website=website,
        parent_org_qid=parent_org_qid,
        industry=industry,
        inception=inception,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_entity(qid: str) -> WikidataEntity:
    """Fetch a single Wikidata entity by QID and extract company-relevant fields.

    Parameters
    ----------
    qid:
        Wikidata QID, e.g. ``"Q185756"`` for Danone.

    Returns
    -------
    WikidataEntity with extracted properties.
    """
    url = _ENTITY_DATA_URL.format(qid=qid)

    async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": "CompanyCarbonLookup/0.1 (https://github.com/company-carbon-lookup)"}) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

    entity = data.get("entities", {}).get(qid, {})
    return _parse_entity(qid, entity)


async def search_entities(name: str, limit: int = 10) -> list[WikidataEntity]:
    """Search Wikidata for entities matching a company name.

    Calls the ``wbsearchentities`` API, then fetches full entity data for
    each result and filters to entities that look like companies (based on
    P31 instance-of, P414 stock exchange, or P1278 LEI).

    Parameters
    ----------
    name:
        Company name to search for.
    limit:
        Maximum number of search results to request from Wikidata.

    Returns
    -------
    List of WikidataEntity objects that appear to be companies.
    """
    params = {
        "action": "wbsearchentities",
        "search": name,
        "type": "item",
        "language": "en",
        "limit": limit,
        "format": "json",
    }

    async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": "CompanyCarbonLookup/0.1 (https://github.com/company-carbon-lookup)"}) as client:
        resp = await client.get(_WIKIDATA_API, params=params)
        resp.raise_for_status()
        search_data = resp.json()

    search_results = search_data.get("search", [])
    if not search_results:
        return []

    entities: list[WikidataEntity] = []

    # Fetch full entity data for each search result
    async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": "CompanyCarbonLookup/0.1 (https://github.com/company-carbon-lookup)"}) as client:
        for result in search_results:
            qid = result.get("id")
            if not qid:
                continue

            try:
                url = _ENTITY_DATA_URL.format(qid=qid)
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()

                entity_data = data.get("entities", {}).get(qid, {})
                claims = entity_data.get("claims", {})

                # Only include entities that look like companies
                if not _is_company_entity(claims):
                    logger.debug("Skipping %s — not a company entity", qid)
                    continue

                entities.append(_parse_entity(qid, entity_data))

            except httpx.HTTPError:
                logger.warning("Failed to fetch entity data for %s", qid, exc_info=True)
                continue

    return entities
