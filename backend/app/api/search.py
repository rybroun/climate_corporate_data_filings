"""
GET /api/search — typeahead / company search endpoint.
Uses Supabase to query the company table via the search_companies() function.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.db import get_pool
from app.models.schemas import SearchResponse, SearchResult

router = APIRouter()


@router.get("/search", response_model=SearchResponse)
async def search_companies(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(5, ge=1, le=20, description="Max results"),
) -> SearchResponse:
    pool = get_pool()

    if pool is None or not pool.available:
        return SearchResponse(results=[])

    # Try the pg_trgm search function first
    rows = pool.rpc("search_companies", {"query": q, "max_results": limit})

    # If RPC returns nothing, fall back to ILIKE
    if not rows:
        rows = pool.select_ilike("company", "canonical_name", f"%{q}%", limit=limit)

    results = [
        SearchResult(
            company_id=str(row.get("company_id", "")),
            canonical_name=row.get("canonical_name", ""),
            domain="",  # Not stored in company table yet
            hq_country=row.get("hq_country", ""),
            logo_initial=row.get("canonical_name", "?")[0],
            match_score=round(float(row.get("similarity", 0.5)), 2),
            match_type="fuzzy_name" if row.get("similarity") else "ilike",
            has_emissions_data=bool(row.get("has_emissions_data", False)),
        )
        for row in rows
    ]

    return SearchResponse(results=results)
