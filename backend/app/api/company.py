"""
Company data endpoints:
  GET /api/company/{company_id}/emissions
  GET /api/company/{company_id}/trend
  GET /api/company/{company_id}/sources
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Path, Query

from app.config import settings
from app.db import get_pool
from app.models.enums import Methodology, SourceAuthority, SourceType, VerificationStatus
from app.models.schemas import (
    ConfidenceDetail,
    EmissionsResponse,
    IntensityDetail,
    SourceItem,
    SourcesResponse,
    TrendPoint,
    TrendResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _build_storage_url(storage_path: str | None) -> str | None:
    if not storage_path or not settings.supabase_url:
        return None
    return f"{settings.supabase_url.rstrip('/')}/storage/v1/object/public/{storage_path}"


def _get_company_name(pool, company_id: str) -> str:
    """Look up company name from the DB, return 'Unknown Company' if not found."""
    if pool is None:
        return "Unknown Company"
    try:
        rows = pool.select("company", company_id=company_id)
        return rows[0].get("canonical_name", "Unknown Company") if rows else "Unknown Company"
    except Exception:
        return "Unknown Company"


def _empty_emissions(company_id: str, company_name: str) -> EmissionsResponse:
    """Return a zeroed emissions response for companies with no data."""
    return EmissionsResponse(
        company_id=company_id,
        canonical_name=company_name,
        reporting_year=0,
        scope_1_tco2e=0,
        scope_2_market_tco2e=0,
        scope_3_total_tco2e=0,
        total_tco2e=0,
        delta_pct=0.0,
        prior_year_total=0,
        methodology=Methodology.OTHER,
        verification_status=VerificationStatus.NONE,
        intensity=IntensityDetail(revenue_tco2e_per_m=0, headcount_tco2e=0, unit_kgco2e=0),
        confidence=ConfidenceDetail(
            score=0,
            note="No emissions data available",
            source_authority=SourceAuthority.THIRD_PARTY_ESTIMATED,
            sources_count=0,
            verified_count=0,
        ),
        last_verified_at=None,
    )


# ---------------------------------------------------------------------------
# GET /company/{company_id}/emissions
# ---------------------------------------------------------------------------

@router.get("/company/{company_id}/emissions", response_model=EmissionsResponse)
async def get_emissions(
    company_id: str = Path(..., description="Company UUID"),
    year: str = Query("latest", description="Reporting year or 'latest'"),
) -> EmissionsResponse:
    pool = get_pool()
    company_name = _get_company_name(pool, company_id)

    if pool is None:
        return _empty_emissions(company_id, company_name)

    try:
        q = pool.table("canonical_disclosure").select("*").eq("company_id", company_id)
        if year == "latest":
            q = q.order("reporting_year", desc=True).limit(1)
        else:
            q = q.eq("reporting_year", int(year)).limit(1)
        disclosure_result = q.execute()
        disclosures = disclosure_result.data if disclosure_result.data else []

        if not disclosures:
            return _empty_emissions(company_id, company_name)

        d = disclosures[0]
        reporting_year = d.get("reporting_year", 2024)

        scope_1 = int(d.get("scope_1_tco2e") or 0)
        scope_2 = int(d.get("scope_2_market_tco2e") or 0)
        scope_3 = int(d.get("scope_3_total_tco2e") or 0)
        total = scope_1 + scope_2 + scope_3

        # Prior year for delta
        prior_result = (
            pool.table("canonical_disclosure").select("*")
            .eq("company_id", company_id).eq("reporting_year", reporting_year - 1)
            .limit(1).execute()
        )
        prior_rows = prior_result.data if prior_result.data else []
        if prior_rows:
            p = prior_rows[0]
            prior_total = int(p.get("scope_1_tco2e") or 0) + int(p.get("scope_2_market_tco2e") or 0) + int(p.get("scope_3_total_tco2e") or 0)
            delta_pct = round(((total - prior_total) / prior_total) * 100, 1) if prior_total else 0.0
        else:
            prior_total = 0
            delta_pct = 0.0

        # Company data for intensity
        company_rows = pool.select("company", company_id=company_id)
        company = company_rows[0] if company_rows else {}
        canonical_name = company.get("canonical_name") or company_name
        revenue = company.get("annual_revenue_eur")
        employees = company.get("employee_count")

        if revenue and revenue > 0:
            rev_intensity = round(total / (revenue / 1_000_000), 1)
        else:
            rev_intensity = 0.0
        headcount_intensity = round(total / employees, 1) if employees and employees > 0 else 0.0
        unit_kgco2e = round((total * 1000) / revenue, 2) if revenue and revenue > 0 else 0.0

        # Confidence
        from app.pipeline.confidence import compute_confidence
        all_disclosures = pool.select("emissions_disclosure", company_id=company_id, reporting_year=reporting_year)
        provenance_rows = []  # data_provenance doesn't have company_id column directly
        confidence_score = compute_confidence(all_disclosures, provenance_rows)

        source_docs = pool.select("source_document", company_id=company_id)
        sources_count = len(source_docs)

        source_authority = d.get("source_authority", "self_reported")
        verification_status = d.get("verification_status", "none")

        return EmissionsResponse(
            company_id=company_id,
            canonical_name=canonical_name,
            reporting_year=reporting_year,
            scope_1_tco2e=scope_1,
            scope_2_market_tco2e=scope_2,
            scope_3_total_tco2e=scope_3,
            total_tco2e=total,
            delta_pct=delta_pct,
            prior_year_total=prior_total,
            methodology=Methodology(d.get("methodology", "other")),
            verification_status=VerificationStatus(verification_status),
            intensity=IntensityDetail(
                revenue_tco2e_per_m=rev_intensity,
                headcount_tco2e=headcount_intensity,
                unit_kgco2e=unit_kgco2e,
            ),
            confidence=ConfidenceDetail(
                score=confidence_score,
                note=f"Based on {sources_count} source(s)",
                source_authority=SourceAuthority(source_authority),
                sources_count=sources_count,
                verified_count=0,
            ),
            last_verified_at=datetime.now(timezone.utc),
        )

    except Exception:
        logger.exception("Error fetching emissions for %s", company_id)
        return _empty_emissions(company_id, company_name)


# ---------------------------------------------------------------------------
# GET /company/{company_id}/trend
# ---------------------------------------------------------------------------

@router.get("/company/{company_id}/trend", response_model=TrendResponse)
async def get_trend(
    company_id: str = Path(..., description="Company UUID"),
    from_year: int = Query(2018, description="Start year"),
    to_year: int = Query(2024, description="End year"),
) -> TrendResponse:
    pool = get_pool()
    if pool is None:
        return TrendResponse(company_id=company_id, trend=[])

    try:
        result = (
            pool.table("canonical_disclosure")
            .select("reporting_year, scope_1_tco2e, scope_2_market_tco2e, scope_3_total_tco2e")
            .eq("company_id", company_id)
            .gte("reporting_year", from_year)
            .lte("reporting_year", to_year)
            .order("reporting_year")
            .execute()
        )
        rows = result.data if result.data else []

        trend = [
            TrendPoint(
                year=r["reporting_year"],
                scope_1=int(r.get("scope_1_tco2e") or 0),
                scope_2_market=int(r.get("scope_2_market_tco2e") or 0),
                scope_3=int(r.get("scope_3_total_tco2e") or 0),
            )
            for r in rows
        ]
        return TrendResponse(company_id=company_id, trend=trend)

    except Exception:
        logger.exception("Error fetching trend for %s", company_id)
        return TrendResponse(company_id=company_id, trend=[])


# ---------------------------------------------------------------------------
# GET /company/{company_id}/sources
# ---------------------------------------------------------------------------

@router.get("/company/{company_id}/sources", response_model=SourcesResponse)
async def get_sources(
    company_id: str = Path(..., description="Company UUID"),
) -> SourcesResponse:
    pool = get_pool()
    if pool is None:
        return SourcesResponse(sources=[])

    try:
        source_docs = pool.select("source_document", company_id=company_id)
        if not source_docs:
            return SourcesResponse(sources=[])

        company_rows = pool.select("company", company_id=company_id)
        company_name = company_rows[0].get("canonical_name", "Company") if company_rows else "Company"

        disclosures = pool.select("emissions_disclosure", company_id=company_id)
        year_verification: dict[int, str] = {}
        for disc in disclosures:
            yr = disc.get("reporting_year")
            vs = disc.get("verification_status", "none")
            if yr:
                year_verification[yr] = vs

        sources: list[SourceItem] = []
        for doc in source_docs:
            source_type_val = doc.get("source_type", "other")
            pub_date = doc.get("publication_date") or "2025-01-01"
            storage_path = doc.get("storage_path") or ""
            original_url = doc.get("original_url") or ""

            # Extract year from publication_date
            try:
                reporting_year = int(str(pub_date)[:4]) - 1  # pub year is usually year after reporting year
            except (ValueError, TypeError):
                reporting_year = 2024

            source_type_label = source_type_val.replace("_", " ").title()
            title = f"{company_name} {source_type_label} {reporting_year}"

            vs = year_verification.get(reporting_year, "none")
            verified = vs in ("limited_assurance", "reasonable_assurance")

            try:
                st_enum = SourceType(source_type_val)
            except ValueError:
                st_enum = SourceType.OTHER

            if isinstance(pub_date, str) and "T" in pub_date:
                pub_date = pub_date.split("T")[0]

            sources.append(SourceItem(
                source_document_id=str(doc.get("source_document_id", "")),
                source_type=st_enum,
                title=title,
                publication_date=str(pub_date),
                page_number=doc.get("page_number"),
                section_reference=doc.get("section_reference") or "",
                reporting_year=reporting_year,
                verified=verified,
                source_authority=SourceAuthority.SELF_REPORTED,
                storage_path=storage_path,
                original_url=original_url,
                storage_url=_build_storage_url(storage_path),
            ))

        return SourcesResponse(sources=sources)

    except Exception:
        logger.exception("Error fetching sources for %s", company_id)
        return SourcesResponse(sources=[])
