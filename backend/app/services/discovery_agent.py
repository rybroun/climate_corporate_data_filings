"""
Document discovery agent using Claude with tool use and Serper search.

Discovers sustainability-relevant PDFs for a company by searching the web,
classifying document types, and downloading the top results.
Falls back to mock data when API keys are not set.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class DiscoveredDocument:
    url: str
    title: str
    source_type: str  # maps to source_type_enum
    file_bytes: bytes | None
    content_hash: str | None
    file_size: int | None
    original_url: str | None = None  # the URL we downloaded from


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_DOCUMENTS = 5
_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
_DOWNLOAD_TIMEOUT = 30.0  # seconds per download

_CLASSIFY_TOOL = {
    "name": "classify_documents",
    "description": "Classify search results into sustainability document types.",
    "input_schema": {
        "type": "object",
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "source_type": {
                            "type": "string",
                            "enum": [
                                "annual_report",
                                "integrated_report",
                                "cdp_response",
                                "transition_plan",
                                "non_financial_statement",
                                "sbti_commitment",
                                "subsidiary_list",
                                "impact_report",
                                "other",
                            ],
                        },
                        "relevance_score": {
                            "type": "number",
                            "description": "0.0 to 1.0 relevance score",
                        },
                    },
                    "required": ["url", "title", "source_type"],
                },
            },
        },
        "required": ["classifications"],
    },
}


# ---------------------------------------------------------------------------
# Serper search
# ---------------------------------------------------------------------------


async def _serper_search(query: str) -> list[dict]:
    """Run a search query via Serper API and return organic results."""
    if not settings.serper_api_key:
        logger.info("No SERPER_API_KEY set, skipping search for: %s", query)
        return []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://google.serper.dev/search",
                headers={
                    "X-API-KEY": settings.serper_api_key,
                    "Content-Type": "application/json",
                },
                json={"q": query, "num": 10},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("organic", [])
    except Exception as e:
        logger.warning("Serper search failed for '%s': %s", query, e)
        return []


# ---------------------------------------------------------------------------
# PDF download
# ---------------------------------------------------------------------------


async def _download_pdf(url: str) -> tuple[bytes | None, str | None]:
    """Download a PDF from a URL. Returns (file_bytes, content_hash) or (None, None)."""
    try:
        async with httpx.AsyncClient(
            timeout=_DOWNLOAD_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "CompanyCarbonLookup/1.0"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

            # Check content type
            content_type = resp.headers.get("content-type", "")
            if "pdf" not in content_type and not url.lower().endswith(".pdf"):
                logger.debug("Skipping non-PDF URL: %s (content-type: %s)", url, content_type)
                return None, None

            file_bytes = resp.content

            # Check file size
            if len(file_bytes) > _MAX_FILE_SIZE:
                logger.warning("Skipping oversized PDF (%d bytes): %s", len(file_bytes), url)
                return None, None

            content_hash = hashlib.sha256(file_bytes).hexdigest()
            return file_bytes, content_hash

    except Exception as e:
        logger.warning("Failed to download PDF from %s: %s", url, e)
        return None, None


def _upload_to_storage(
    company_id: str,
    source_type: str,
    year: int,
    content_hash: str,
    file_bytes: bytes,
) -> bool:
    """Upload a PDF to Supabase Storage. Returns True on success."""
    from app.db import get_pool

    pool = get_pool()
    if not pool or not pool.available:
        logger.debug("No Supabase pool available, skipping storage upload")
        return False

    storage = pool.storage()
    if not storage:
        logger.debug("No Supabase storage available, skipping upload")
        return False

    path = f"{company_id}/{source_type}/{year}/{content_hash}.pdf"
    try:
        storage.from_("sustainability-sources").upload(
            path,
            file_bytes,
            file_options={"content-type": "application/pdf"},
        )
        logger.info("Uploaded PDF to storage: %s", path)
        return True
    except Exception as e:
        # Duplicate uploads return a 409; treat as success
        if "Duplicate" in str(e) or "already exists" in str(e):
            logger.debug("PDF already in storage: %s", path)
            return True
        logger.warning("Failed to upload PDF to storage: %s", e)
        return False


# ---------------------------------------------------------------------------
# Claude classification
# ---------------------------------------------------------------------------


async def _classify_with_claude(search_results: list[dict]) -> list[dict]:
    """Use Claude to classify search results by document source_type."""
    if not settings.anthropic_api_key:
        # Simple heuristic classification fallback
        return _heuristic_classify(search_results)

    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Build context from search results
    items_text = []
    for i, result in enumerate(search_results):
        items_text.append(
            f"{i + 1}. URL: {result.get('link', '')}\n"
            f"   Title: {result.get('title', '')}\n"
            f"   Snippet: {result.get('snippet', '')}"
        )

    user_content = (
        "Classify these search results into sustainability document types. "
        "Only include results that are actual sustainability-related documents "
        "(reports, CDP responses, transition plans, etc.). Exclude news articles, "
        "press releases, and generic web pages.\n\n"
        + "\n\n".join(items_text)
    )

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            temperature=0,
            system=(
                "You are a document classifier specializing in corporate sustainability disclosures. "
                "Classify search results into document types: annual_report, integrated_report, "
                "cdp_response, transition_plan, non_financial_statement, sbti_commitment, "
                "subsidiary_list, impact_report, or other. Only include relevant documents."
            ),
            messages=[{"role": "user", "content": user_content}],
            tools=[_CLASSIFY_TOOL],
        )

        for block in response.content:
            if block.type == "tool_use":
                return block.input.get("classifications", [])

    except Exception as e:
        logger.warning("Claude classification failed: %s", e)

    return _heuristic_classify(search_results)


def _heuristic_classify(search_results: list[dict]) -> list[dict]:
    """Simple keyword-based classification fallback."""
    classifications = []

    for result in search_results:
        url = result.get("link", "")
        title = result.get("title", "").lower()
        snippet = result.get("snippet", "").lower()
        combined = f"{title} {snippet} {url.lower()}"

        # Skip non-PDF or irrelevant results
        if not any(kw in combined for kw in ["sustainability", "annual report", "cdp", "climate", "esg", "emissions"]):
            continue

        # Classify based on keywords
        source_type = "other"
        if "cdp" in combined and ("response" in combined or "climate" in combined):
            source_type = "cdp_response"
        elif "transition plan" in combined or "climate plan" in combined:
            source_type = "transition_plan"
        elif "integrated" in combined and "report" in combined:
            source_type = "integrated_report"
        elif "non-financial" in combined or "dpef" in combined or "nfrd" in combined:
            source_type = "non_financial_statement"
        elif "annual report" in combined or "universal registration" in combined:
            source_type = "annual_report"
        elif "sbti" in combined or "science based target" in combined:
            source_type = "sbti_commitment"
        elif "subsidiaries" in combined or "subsidiary" in combined:
            source_type = "subsidiary_list"
        elif any(kw in combined for kw in ["sustainability report", "esg report", "impact report"]):
            source_type = "impact_report"

        classifications.append({
            "url": url,
            "title": result.get("title", ""),
            "source_type": source_type,
            "relevance_score": 0.7,
        })

    return classifications[:_MAX_DOCUMENTS]


# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------


def _mock_documents(company_name: str) -> list[DiscoveredDocument]:
    """Return mock discovered documents for testing without API keys."""
    slug = company_name.lower().replace(' ', '-')
    return [
        DiscoveredDocument(
            url=f"https://example.com/{slug}/annual-report-2024.pdf",
            title=f"{company_name} Integrated Annual Report 2024",
            source_type="integrated_report",
            file_bytes=None,
            content_hash=None,
            file_size=None,
            original_url=f"https://example.com/{slug}/annual-report-2024.pdf",
        ),
        DiscoveredDocument(
            url=f"https://example.com/{slug}/cdp-response-2024.pdf",
            title=f"{company_name} CDP Climate Change Response 2024",
            source_type="cdp_response",
            file_bytes=None,
            content_hash=None,
            file_size=None,
            original_url=f"https://example.com/{slug}/cdp-response-2024.pdf",
        ),
        DiscoveredDocument(
            url=f"https://example.com/{slug}/transition-plan-2023.pdf",
            title=f"{company_name} Climate Transition Plan 2023",
            source_type="transition_plan",
            file_bytes=None,
            content_hash=None,
            file_size=None,
            original_url=f"https://example.com/{slug}/transition-plan-2023.pdf",
        ),
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def discover_documents(
    company_name: str,
    website: str | None,
    company_id: str,
) -> list[DiscoveredDocument]:
    """Discover sustainability-relevant documents for a company.

    Searches the web using Serper, classifies results using Claude,
    and downloads top PDF results. Falls back to mock data when API keys
    are not available.

    Parameters
    ----------
    company_name:
        The company's canonical name.
    website:
        The company's official website URL (from Wikidata), if known.
    company_id:
        Internal company UUID.

    Returns
    -------
    List of DiscoveredDocument objects (max 5).
    """
    if not settings.serper_api_key and not settings.anthropic_api_key:
        logger.info("No API keys set, returning mock discovered documents")
        return _mock_documents(company_name)

    # Build search queries
    queries = [
        f'"{company_name}" sustainability report filetype:pdf',
        f'"{company_name}" CDP climate change response filetype:pdf',
    ]

    if website:
        # Extract domain from website URL
        from urllib.parse import urlparse
        parsed = urlparse(website)
        domain = parsed.netloc or parsed.path
        if domain:
            queries.append(f"site:{domain} annual report sustainability filetype:pdf")

    # Run all searches
    all_results: list[dict] = []
    seen_urls: set[str] = set()

    for query in queries:
        results = await _serper_search(query)
        for r in results:
            url = r.get("link", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(r)

    if not all_results:
        logger.info("No search results found for %s, returning mock documents", company_name)
        return _mock_documents(company_name)

    # Classify results
    classifications = await _classify_with_claude(all_results)

    if not classifications:
        logger.info("No relevant documents classified for %s", company_name)
        return _mock_documents(company_name)

    # Sort by relevance and take top N
    classifications.sort(key=lambda c: c.get("relevance_score", 0), reverse=True)
    top_docs = classifications[:_MAX_DOCUMENTS]

    # Download PDFs and upload to Supabase Storage
    from datetime import datetime, timezone

    documents: list[DiscoveredDocument] = []

    for doc_info in top_docs:
        url = doc_info.get("url", "")
        title = doc_info.get("title", "Unknown Document")
        source_type = doc_info.get("source_type", "other")

        # Only attempt download for URLs that look like PDFs
        file_bytes = None
        content_hash = None
        if url.lower().endswith(".pdf"):
            file_bytes, content_hash = await _download_pdf(url)

            # Upload to Supabase Storage if download succeeded
            if file_bytes and content_hash:
                year = datetime.now(timezone.utc).year
                _upload_to_storage(company_id, source_type, year, content_hash, file_bytes)

        documents.append(
            DiscoveredDocument(
                url=url,
                title=title,
                source_type=source_type,
                file_bytes=file_bytes,
                content_hash=content_hash,
                file_size=len(file_bytes) if file_bytes else None,
                original_url=url,
            )
        )

    logger.info(
        "Discovered %d documents for %s (%d with content)",
        len(documents),
        company_name,
        sum(1 for d in documents if d.file_bytes is not None),
    )

    return documents
