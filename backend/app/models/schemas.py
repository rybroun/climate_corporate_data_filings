"""
Pydantic models for all API request/response shapes.
Matches the JSON structures defined in requirements.md section 4.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.enums import Methodology, SourceAuthority, SourceType, VerificationStatus


# ---------------------------------------------------------------------------
# 4.1 Search / Typeahead
# ---------------------------------------------------------------------------

class SearchResult(BaseModel):
    company_id: str
    canonical_name: str
    domain: str
    hq_country: str
    logo_initial: str
    match_score: float
    match_type: str
    has_emissions_data: bool


class SearchResponse(BaseModel):
    results: list[SearchResult]


# ---------------------------------------------------------------------------
# 4.2 Resolve (pipeline trigger)
# ---------------------------------------------------------------------------

class ResolveRequest(BaseModel):
    query: str
    wikidata_qid: Optional[str] = None


class ResolveResponse(BaseModel):
    job_id: str
    stream_url: str


# ---------------------------------------------------------------------------
# 4.3 Pipeline Stream (SSE)
# ---------------------------------------------------------------------------

class SSEStepEvent(BaseModel):
    step: int
    step_name: str
    status: str
    log_line: str
    documents_found: Optional[int] = None
    company_id: Optional[str] = None


class SSECompleteEvent(BaseModel):
    company_id: str
    documents_processed: int
    years_covered: list[int]


# ---------------------------------------------------------------------------
# 4.4 Company Emissions
# ---------------------------------------------------------------------------

class IntensityDetail(BaseModel):
    revenue_tco2e_per_m: float
    headcount_tco2e: float
    unit_kgco2e: float


class ConfidenceDetail(BaseModel):
    score: int
    note: str
    source_authority: SourceAuthority
    sources_count: int
    verified_count: int


class EmissionsResponse(BaseModel):
    company_id: str
    canonical_name: str
    reporting_year: int
    scope_1_tco2e: int
    scope_2_market_tco2e: int
    scope_3_total_tco2e: int
    total_tco2e: int
    delta_pct: float
    prior_year_total: int
    methodology: Methodology
    verification_status: VerificationStatus
    intensity: IntensityDetail
    confidence: ConfidenceDetail
    last_verified_at: datetime | None = None


# ---------------------------------------------------------------------------
# 4.5 Company Trend
# ---------------------------------------------------------------------------

class TrendPoint(BaseModel):
    year: int
    scope_1: int
    scope_2_market: int
    scope_3: int


class TrendResponse(BaseModel):
    company_id: str
    trend: list[TrendPoint]


# ---------------------------------------------------------------------------
# 4.6 Company Sources
# ---------------------------------------------------------------------------

class SourceItem(BaseModel):
    source_document_id: str
    source_type: SourceType
    title: str
    publication_date: str
    page_number: Optional[int] = None
    section_reference: str
    reporting_year: int
    verified: bool
    source_authority: SourceAuthority
    storage_path: Optional[str] = None
    original_url: Optional[str] = None
    storage_url: Optional[str] = None


class SourcesResponse(BaseModel):
    sources: list[SourceItem]
