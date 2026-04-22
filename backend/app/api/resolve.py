"""
Pipeline resolution endpoints:
  POST /api/resolve       -- kick off the pipeline, return job_id
  GET  /api/resolve/{job_id}/stream -- SSE endpoint streaming pipeline progress
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Path
from sse_starlette.sse import EventSourceResponse

from app.models.schemas import ResolveRequest, ResolveResponse
from app.pipeline.orchestrator import create_job, get_job, run_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()

# Freshness threshold: skip pipeline if company was verified within this period
_FRESHNESS_DAYS = 7


# ---------------------------------------------------------------------------
# Freshness check helper
# ---------------------------------------------------------------------------

async def _check_freshness(query: str) -> str | None:
    """Check if a company matching this query was verified recently.

    Returns the company_id if fresh data exists, None otherwise.
    """
    try:
        from app.db import get_pool
        pool = get_pool()
    except (RuntimeError, ImportError):
        return None

    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=_FRESHNESS_DAYS)

        # Check by canonical name (case-insensitive)
        row = await pool.fetchrow(
            """
            SELECT company_id, updated_at
            FROM company
            WHERE LOWER(canonical_name) = LOWER($1)
              AND updated_at > $2
            LIMIT 1
            """,
            query.strip(),
            cutoff,
        )

        if row:
            company_id = str(row["company_id"])
            logger.info(
                "Freshness check passed for '%s': company_id=%s, updated=%s",
                query,
                company_id[:8],
                row["updated_at"],
            )
            return company_id

    except Exception as e:
        logger.debug("Freshness check failed: %s", e)

    return None


# ---------------------------------------------------------------------------
# POST /resolve
# ---------------------------------------------------------------------------

@router.post("/resolve", response_model=ResolveResponse)
async def resolve_company(body: ResolveRequest) -> ResolveResponse:
    """
    Kick off the entity-resolution + extraction pipeline.

    If the company was verified within the last 7 days, returns the
    existing company_id immediately without running the pipeline.
    Otherwise, creates a PipelineJob, starts the pipeline as a
    background task, and returns the job_id + stream URL.
    """
    # Freshness check: skip pipeline if data is recent
    fresh_company_id = await _check_freshness(body.query)
    if fresh_company_id:
        # Create a job that completes immediately
        job = create_job(body.query, body.wikidata_qid)
        job.company_id = fresh_company_id
        job.status = "complete"

        # Push a complete event so the stream works
        await job.queue.put({
            "event": "complete",
            "data": json.dumps({
                "company_id": fresh_company_id,
                "documents_processed": 0,
                "years_covered": [],
            }),
        })

        return ResolveResponse(
            job_id=job.job_id,
            stream_url=f"/api/resolve/{job.job_id}/stream",
        )

    # Create job and start pipeline in background
    job = create_job(body.query, body.wikidata_qid)
    asyncio.create_task(run_pipeline(job))

    return ResolveResponse(
        job_id=job.job_id,
        stream_url=f"/api/resolve/{job.job_id}/stream",
    )


# ---------------------------------------------------------------------------
# GET /resolve/{job_id}/stream  (SSE)
# ---------------------------------------------------------------------------

@router.get("/resolve/{job_id}/stream")
async def stream_pipeline(
    job_id: str = Path(..., description="Job UUID from POST /resolve"),
) -> EventSourceResponse:
    """
    SSE endpoint streaming pipeline progress events.

    Consumes events from the job's asyncio.Queue, yielding them as SSE
    until a 'complete' event is received.
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    async def event_generator():
        while True:
            try:
                event = await asyncio.wait_for(job.queue.get(), timeout=300.0)
            except asyncio.TimeoutError:
                # Send a keepalive comment
                yield {"comment": "keepalive"}
                continue

            yield event

            # Check if this is the terminal event
            event_type = event.get("event", "")
            if event_type == "complete":
                break

    return EventSourceResponse(event_generator())
