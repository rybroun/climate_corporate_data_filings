# Company Carbon Lookup — Requirements Specification

## 1. Product Summary

A web application where a user enters a company name or Wikidata QID and receives a verified carbon footprint derived from public data. The system resolves the entity, crawls the web for sustainability documents, extracts structured emissions data, and presents results with full source citations.

---

## 2. User Flow

```
[Search] → [Entity Resolution] → [Document Discovery] → [Extraction] → [Results]
```

The entire pipeline runs on-the-fly per request. The user sees progressive updates as each stage completes.

---

## 3. Screens

### 3.1 Home

**Purpose:** Entry point. User searches or picks a sample company.

**Components:**
- Search bar accepting: company name (free text), Wikidata QID, URL
- Live autocomplete dropdown (max 5 results) querying existing COMPANY rows
  - Each suggestion shows: logo initial, canonical_name, domain, match score
  - Match score comes from the ER reranker
- "Resolve" button (Enter key shortcut)
- Search hint: "Press ↵ to resolve · Accepts name, URL, ticker, or Wikidata QID"
- Entity Resolution Pipeline card (7 steps, idle state)
- "Try a sample company" section — grid of pre-seeded companies with source-type tags

**API dependencies:**
- `GET /api/search?q={query}` — typeahead against COMPANY table

### 3.2 Searching

**Purpose:** Show the ER + extraction pipeline running in real-time.

**Components:**
- Header: "Resolving {Company Name}..." (company name in `--forest` color)
- Status chip: spinner + current step name + "N of 7"
- Pipeline card — same 7 steps, each transitioning through: `idle` → `active` → `done`
- Live worker log — black terminal-style panel streaming extraction progress

**Pipeline steps:**
1. Parse query — LLM normalizes input, preserves legal suffix
2. Match entity — local DB lookup, then Wikidata if needed
3. Fetch public filings — Claude Agent SDK discovers documents via Serper + website crawl
4. Extract emissions — PyMuPDF + Claude structured extraction
5. Normalize units — convert to tCO₂e
6. Classify Scope 1/2/3 — map native categories to GHG Protocol
7. Store & cache — write-back to all data model tables

**Behavior:**
- Steps advance based on real backend progress (SSE), not timers
- Worker log lines stream from the backend as they happen
- On completion (all 7 steps done), 300ms settle then transition to Results

**API dependencies:**
- `POST /api/resolve` — kicks off the full pipeline, returns a `job_id`
- `GET /api/resolve/{job_id}/stream` — SSE endpoint streaming pipeline progress

**SSE event format:**
```json
{
  "step": 3,
  "step_name": "Fetch public filings",
  "status": "running",
  "log_line": "✓ CDP Climate Change Response 2024 (2.6MB)",
  "documents_found": 4,
  "company_id": "uuid"
}
```

### 3.3 Results

**Purpose:** Present the verified carbon footprint with full citations and confidence scoring.

**Layout (top to bottom):**

1. **Back link** — "← New search", returns to Home

2. **Result header**
   - Company logo tile (52×52, initial on black, swap for real logo via Clearbit when available)
   - Company name (32px), ticker/domain/FY meta line
   - Chips: `Entity resolved` (moss dot), `GHG Protocol · Market-based`, `{N} sources cited`, `Updated {X} days ago`
   - Data confidence card (right-aligned): score out of 100, fill bar, note

3. **Headline card** — two-column grid
   - Left: "TOTAL EMISSIONS · {YEAR}" kicker, massive number (72px) with MtCO₂e unit, YoY delta chip (green=decrease, rust=increase), comparison to prior year
   - Right: 3-row intensity list (revenue, headcount, per-unit)

4. **Results grid** — two-column (1.2fr / 1fr)
   - Scope breakdown card: Scope 1/2/3 rows with label, description, value/percentage, horizontal bar
   - Year-over-year trend card: stacked bar chart (default) or line chart (togglable), 7-year range, legend

5. **Sources card** — list of cited source documents
   - Each row: source type badge (10-K, CDP, SUST, SBTi, NEWS, NGO, EST), title, page/section/year/verification meta, "Open excerpt →" link
   - Verification status: ✓ verified (forest green) or ◇ estimated (amber)

**API dependencies:**
- `GET /api/company/{company_id}/emissions?year=latest` — canonical coalesced emissions
- `GET /api/company/{company_id}/trend?from=2018&to=2024` — multi-year scope breakdown
- `GET /api/company/{company_id}/sources` — cited source documents with provenance

**Data derivation rules:**

| UI element | Data source |
|---|---|
| Total emissions | Coalesced `scope_1 + scope_2_market + scope_3_total` from `EMISSIONS_DISCLOSURE` |
| YoY delta | Compare current year total vs prior year total |
| Scope breakdown | Same coalesced disclosure row |
| Intensity · revenue | `total_tco2e / annual_revenue_eur * 1e6` |
| Intensity · headcount | `total_tco2e / employee_count` |
| Trend data | `EMISSIONS_DISCLOSURE` grouped by `reporting_year`, coalesced per year |
| Sources cited | `SOURCE_DOCUMENT` joined via `EMISSIONS_DISCLOSURE.source_document_id` + `DATA_PROVENANCE` |
| Confidence score | Derived from: `source_authority` weight, `verification_status`, number of corroborating sources, `DATA_PROVENANCE.confidence` average |
| "Updated X days ago" | `now() - MAX(last_verified_at)` across disclosure rows |
| Verified vs estimated | `source_authority IN (self_reported_verified, regulatory_filing)` → verified; `third_party_estimated` → estimated |

---

## 4. API Specification

### 4.1 Search / Typeahead

```
GET /api/search?q={query}&limit=5
```

Response:
```json
{
  "results": [
    {
      "company_id": "uuid",
      "canonical_name": "Danone S.A.",
      "domain": "danone.com",
      "hq_country": "FR",
      "logo_initial": "D",
      "match_score": 0.94,
      "match_type": "fuzzy_name",
      "has_emissions_data": true
    }
  ]
}
```

Backed by: pg_trgm similarity on `canonical_name`, `legal_name`, unnested `aliases`. If `has_emissions_data` is true, the frontend can skip the pipeline and go straight to Results.

### 4.2 Resolve (pipeline trigger)

```
POST /api/resolve
Body: { "query": "Danone S.A.", "wikidata_qid": null }
```

Response:
```json
{
  "job_id": "uuid",
  "stream_url": "/api/resolve/{job_id}/stream"
}
```

### 4.3 Pipeline Stream (SSE)

```
GET /api/resolve/{job_id}/stream
Accept: text/event-stream
```

Events:
```
event: step
data: {"step": 1, "step_name": "Parse query", "status": "done", "log_line": "tokens=[\"danone\"]", "company_id": null}

event: step
data: {"step": 2, "step_name": "Match entity", "status": "done", "log_line": "resolved = Danone S.A. (BN.PA)", "company_id": "uuid"}

event: step
data: {"step": 3, "step_name": "Fetch public filings", "status": "running", "log_line": "✓ Danone IAR 2024 (14.4MB)", "documents_found": 3}

...

event: complete
data: {"company_id": "uuid", "documents_processed": 6, "years_covered": [2020, 2021, 2022, 2023, 2024]}
```

### 4.4 Company Emissions

```
GET /api/company/{company_id}/emissions?year=latest
```

Response:
```json
{
  "company_id": "uuid",
  "canonical_name": "Danone S.A.",
  "reporting_year": 2024,
  "scope_1_tco2e": 900000,
  "scope_2_market_tco2e": 1100000,
  "scope_3_total_tco2e": 22700000,
  "total_tco2e": 24700000,
  "delta_pct": -6.2,
  "prior_year_total": 26332000,
  "methodology": "ghg_protocol_corporate",
  "verification_status": "limited_assurance",
  "intensity": {
    "revenue_tco2e_per_m": 895,
    "headcount_tco2e": 275,
    "unit_kgco2e": 0.31
  },
  "confidence": {
    "score": 88,
    "note": "Primary source verified · CDP A- disclosure",
    "source_authority": "self_reported_verified",
    "sources_count": 3,
    "verified_count": 3
  },
  "last_verified_at": "2026-04-20T14:30:00Z"
}
```

Backed by: the canonical-metric coalesce view/function over `EMISSIONS_DISCLOSURE`.

### 4.5 Company Trend

```
GET /api/company/{company_id}/trend?from=2018&to=2024
```

Response:
```json
{
  "company_id": "uuid",
  "trend": [
    { "year": 2018, "scope_1": 1200000, "scope_2_market": 1700000, "scope_3": 27900000 },
    { "year": 2019, "scope_1": 1100000, "scope_2_market": 1600000, "scope_3": 27100000 }
  ]
}
```

### 4.6 Company Sources

```
GET /api/company/{company_id}/sources
```

Response:
```json
{
  "sources": [
    {
      "source_document_id": "uuid",
      "source_type": "integrated_report",
      "title": "Danone Universal Registration Document 2024",
      "publication_date": "2025-03-15",
      "page_number": 148,
      "section_reference": "Carbon footprint",
      "reporting_year": 2024,
      "verified": true,
      "source_authority": "self_reported_verified",
      "storage_path": "sustainability-sources/uuid/integrated_report/2024/sha256-xxx.pdf",
      "original_url": "https://danone.com/..."
    }
  ]
}
```

---

## 5. Confidence Score Derivation

The confidence score (0–100) displayed on the Results page is a weighted composite:

| Signal | Weight | Scoring |
|---|---|---|
| Source authority | 40% | self_reported_verified=100, self_reported=70, regulatory_filing=90, third_party_estimated=40 |
| Verification status | 25% | reasonable_assurance=100, limited_assurance=80, none=30 |
| Source count | 15% | 1 source=40, 2=70, 3+=100 |
| Extraction confidence | 20% | Average `DATA_PROVENANCE.confidence` across all provenance rows for this company-year |

Formula: `score = Σ(weight_i × signal_i)`, clamped to [0, 100].

---

## 6. Design Tokens (from handoff)

All defined in `design_handoff_company_carbon_lookup/styles.css`. Key values:

- **Canvas:** `--bg: #F7F5F1`, `--surface: #FFFFFF`
- **Ink:** `--ink: #141815`, `--ink-2: #3A3F3B`, `--ink-3: #6B716C`, `--ink-4: #9AA09B`
- **Accent:** `--forest: oklch(0.35 0.06 155)`, `--moss: oklch(0.55 0.05 155)`, `--sage-bg: oklch(0.93 0.02 155)`
- **Status:** `--amber: oklch(0.72 0.12 75)` (estimated), `--rust: oklch(0.58 0.12 40)` (increase)
- **Type:** Inter Tight (headings), Inter (body), JetBrains Mono (data/kickers)
- **Radii:** 6px / 10px / 14px
- **Max width:** 1180px, 32px horizontal padding

---

## 7. Sample Data for Development

Six pre-seeded companies for the Home screen sample grid:
- Nestlé S.A. (NESN.SW, CDP + Sustainability Report)
- Danone S.A. (BN.PA, Annual Filing + CDP)
- Cargill, Incorporated (Private, Sustainability Report + News)
- Unilever PLC (ULVR.L, CDP + Annual Filing)
- PepsiCo, Inc. (PEP, SEC 10-K + CDP)
- Mondelēz International (MDLZ, SEC 10-K + Sustainability Report)

These should be seeded into the COMPANY table. For v1 development, the frontend can use the `EMISSIONS_DATA` fixtures from `app.jsx` while the backend pipeline is being built.

---

## 8. Non-Functional Requirements

- **Latency:** Search typeahead < 200ms. Full pipeline (cold start, no cached data) target < 3 minutes.
- **Progressive updates:** User sees pipeline progress within 1s of job start. Results appear incrementally.
- **Idempotency:** Re-resolving the same company returns cached results (skips pipeline if data exists and `last_verified_at` is within 7 days).
- **Error handling:** If document discovery finds nothing, show an empty state with "No public sustainability data found for {company}. Try uploading a document manually." (manual upload is future scope).
