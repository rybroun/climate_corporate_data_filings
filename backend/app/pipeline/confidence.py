"""
Confidence score computation.

Implements the weighted composite formula from requirements.md section 5:
    score = source_authority (40%) + verification_status (25%)
          + source_count (15%) + extraction_confidence (20%)

Result is clamped to [0, 100].
"""

from __future__ import annotations

from typing import Any, Sequence


# -- Signal scoring maps -----------------------------------------------------

_SOURCE_AUTHORITY_SCORES: dict[str, int] = {
    "self_reported_verified": 100,
    "regulatory_filing": 90,
    "self_reported": 70,
    "third_party_estimated": 40,
}

_VERIFICATION_STATUS_SCORES: dict[str, int] = {
    "reasonable_assurance": 100,
    "limited_assurance": 80,
    "none": 30,
}

_SOURCE_COUNT_SCORES: dict[int, int] = {
    1: 40,
    2: 70,
    # 3+ handled separately
}


def _source_count_score(n: int) -> int:
    if n >= 3:
        return 100
    return _SOURCE_COUNT_SCORES.get(n, 0)


# -- Public API --------------------------------------------------------------

def compute_confidence(
    disclosures: Sequence[dict[str, Any]],
    provenance_rows: Sequence[dict[str, Any]],
) -> int:
    """
    Compute the confidence score for a set of emission disclosures.

    Parameters
    ----------
    disclosures:
        Rows from EMISSIONS_DISCLOSURE. Each dict should include at minimum:
        - ``source_authority`` (str): one of the SourceAuthority enum values
        - ``verification_status`` (str): one of the VerificationStatus enum values

    provenance_rows:
        Rows from DATA_PROVENANCE. Each dict should include:
        - ``confidence`` (float | int): extraction-level confidence 0-100

    Returns
    -------
    int
        Clamped composite score in [0, 100].
    """

    if not disclosures:
        return 0

    # --- Source authority (40%) ---
    # Use the best (highest-scoring) authority across all disclosures.
    authority_scores = [
        _SOURCE_AUTHORITY_SCORES.get(d.get("source_authority", ""), 0)
        for d in disclosures
    ]
    source_authority_signal = max(authority_scores) if authority_scores else 0

    # --- Verification status (25%) ---
    # Use the best verification level across disclosures.
    verification_scores = [
        _VERIFICATION_STATUS_SCORES.get(d.get("verification_status", ""), 0)
        for d in disclosures
    ]
    verification_signal = max(verification_scores) if verification_scores else 0

    # --- Source count (15%) ---
    source_count_signal = _source_count_score(len(disclosures))

    # --- Extraction confidence (20%) ---
    if provenance_rows:
        confidences = [
            float(r.get("confidence", 0))
            for r in provenance_rows
            if r.get("confidence") is not None
        ]
        extraction_signal = sum(confidences) / len(confidences) if confidences else 0.0
    else:
        extraction_signal = 0.0

    # --- Weighted composite ---
    score = (
        0.40 * source_authority_signal
        + 0.25 * verification_signal
        + 0.15 * source_count_signal
        + 0.20 * extraction_signal
    )

    return int(max(0, min(100, round(score))))
