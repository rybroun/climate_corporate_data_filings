"""
Serper API client for web search.

Used by the document discovery pipeline to find sustainability reports,
CDP responses, and other climate disclosure documents on the web.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SerperResult:
    title: str
    url: str
    snippet: str
    position: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def web_search(query: str, num: int = 10) -> list[SerperResult]:
    """Perform a web search via the Serper API.

    Parameters
    ----------
    query:
        The search query string (e.g. ``"Danone sustainability report filetype:pdf"``).
    num:
        Maximum number of organic results to request.

    Returns
    -------
    List of SerperResult objects parsed from the ``organic`` array.

    Raises
    ------
    httpx.HTTPStatusError
        If the Serper API returns a non-2xx status code.
    ValueError
        If the Serper API key is not configured.
    """
    if not settings.serper_api_key:
        raise ValueError(
            "Serper API key is not configured. "
            "Set SERPER_API_KEY in your environment or .env file."
        )

    headers = {
        "X-API-KEY": settings.serper_api_key,
        "Content-Type": "application/json",
    }

    payload = {
        "q": query,
        "num": num,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://google.serper.dev/search",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    organic = data.get("organic", [])
    results: list[SerperResult] = []

    for item in organic:
        results.append(
            SerperResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
                position=item.get("position", len(results) + 1),
            )
        )

    logger.info("Serper search for %r returned %d results", query, len(results))
    return results
