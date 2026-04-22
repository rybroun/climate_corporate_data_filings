# Agent: Backend

## Role

Build the FastAPI application that serves the frontend and orchestrates the full ER → Discovery → Extraction → Write-back pipeline. You own everything between the HTTP boundary and the database.

## Tech Stack

- **FastAPI** (Python 3.12+) — API server, SSE streaming
- **Claude Agent SDK** — agentic document discovery
- **Claude API** (tool use) — structured extraction from PDFs, input normalization
- **PyMuPDF (fitz)** — PDF text/table extraction
- **Serper API** — web search for document discovery
- **Playwright** — headless browser for JS-rendered sustainability pages
- **httpx** — async HTTP client for Wikidata API (free, no key needed)
- **asyncpg** or **Supabase Python client** — database access
- **Supabase Storage Python client** — blob upload/download

## Responsibilities

### API Endpoints (priority 1 — unblocks frontend)

Implement the endpoints defined in `requirements.md` §4:

1. **`GET /api/search?q={query}&limit=5`** — typeahead search
   - Query the `company_search` view/function (pg_trgm similarity)
   - Return match scores from the reranker
   - Include `has_emissions_data` flag (check if any non-withdrawn disclosure exists)

2. **`POST /api/resolve`** — kick off the full pipeline
   - Accept `{ "query": "...", "wikidata_qid": "..." }`
   - If company already exists with fresh data (`last_verified_at` within 7 days), return immediately with `company_id`
   - Otherwise, create a background job and return `{ "job_id": "...", "stream_url": "..." }`

3. **`GET /api/resolve/{job_id}/stream`** — SSE pipeline progress
   - Stream step-by-step progress as the pipeline runs
   - Each event includes: step number, step name, status, log line, intermediate results
   - Terminal event: `complete` with `company_id` and summary

4. **`GET /api/company/{company_id}/emissions?year=latest`** — canonical emissions
   - Query the `canonical_disclosure` view
   - Compute intensity metrics from `company.annual_revenue_eur` + `company.employee_count`
   - Compute confidence score per `requirements.md` §5
   - Compute YoY delta by comparing current vs prior year

5. **`GET /api/company/{company_id}/trend?from=2018&to=2024`** — multi-year trend
   - Query `canonical_disclosure` grouped by `reporting_year`

6. **`GET /api/company/{company_id}/sources`** — cited source documents
   - Join `source_document` through `emissions_disclosure.source_document_id` + `data_provenance`

### Pipeline Steps (priority 2)

Each step in the pipeline is a discrete function. They run sequentially within a job, streaming progress to the SSE endpoint.

**Step 1: Parse query**
- Call Claude API to normalize user input
- Output: `{ normalized_name, legal_suffix, inferred_jurisdiction, input_type }`
- Preserve legal suffix as jurisdiction signal

**Step 2: Match entity**
- Local DB: pg_trgm search on company table
- If no match: call Wikidata API (`wbsearchentities?search={name}&type=item&language=en`), filter to company entities, extract identity properties (P1448, P17, P414, P1278, P856)
- Persist reranker outputs to `er_match_log`
- Create or update COMPANY row with OC data
- Output: `company_id`

**Step 3: Fetch public filings** (agentic)
- Use Claude Agent SDK with these tools:
  - `web_search(query)` — Serper API
  - `fetch_page(url)` — Playwright or httpx
  - `extract_links(html)` — BeautifulSoup link extraction
  - `download_pdf(url)` — download, hash, check dedup
  - `classify_document(url, link_text, context)` — Claude call to determine `source_type`
- Agent prompt should search: company website sustainability section, Serper for CDP/SBTi/B Corp
- Guardrails: max 50 fetches, 5-minute timeout, stay on-domain + known registries
- Output: list of `SOURCE_DOCUMENT` rows created

**Step 4: Extract emissions**
- For each downloaded PDF:
  - Phase 1: PyMuPDF → `{ page_number, text_blocks[], tables[] }` per page
  - Phase 2: Send page chunks to Claude API with tool use
  - Page classification first: identify which pages contain emissions vs targets vs governance
  - Per-table extraction passes (emissions, targets, programs, governance, certifications)
- Output: structured JSON per pass matching data model schema

**Step 5: Normalize units**
- Convert all extracted values to tCO₂e
- Handle common units: ktCO₂, MtCO₂, tCO₂, kgCO₂e
- Log conversions to worker log

**Step 6: Classify Scope 1/2/3**
- Run the category mapping LLM step:
  - Collect unique `native_category` values
  - Present alongside GHG Protocol reference table
  - Produce `COMPANY_CATEGORY_MAPPING` rows with `allocation_pct` and `rationale`
- Flag ambiguous mappings (confidence < 0.8) in provenance

**Step 7: Store & cache**
- Write-back in dependency order: COMPANY → SOURCE_DOCUMENT → EMISSIONS_DISCLOSURE → LINE_ITEMS → MAPPINGS → TARGETS → PROGRAMS → CERTIFICATIONS → PROVENANCE
- Use upsert (`ON CONFLICT DO UPDATE`) per dedup keys in `requirements.md` §5.2
- Update `company.governance_last_verified_at` and disclosure `last_verified_at`

### Confidence Score (priority 2)

Implement the formula from `requirements.md` §5:
```python
def compute_confidence(disclosures, provenance_rows):
    authority_score = max(AUTHORITY_WEIGHTS[d.source_authority] for d in disclosures)
    verification_score = max(VERIFICATION_WEIGHTS[d.verification_status] for d in disclosures)
    source_count_score = min(len(disclosures) / 3, 1.0) * 100
    extraction_score = mean(p.confidence for p in provenance_rows) * 100
    return round(0.4 * authority_score + 0.25 * verification_score + 0.15 * source_count_score + 0.20 * extraction_score)
```

## Key Constraints

- **No blocking the user:** The resolve endpoint returns immediately; all heavy work happens in the background job with SSE streaming.
- **Idempotency:** Re-resolving a company with fresh data (< 7 days) skips the pipeline.
- **Provenance on everything:** Every extracted value gets a `DATA_PROVENANCE` row with page number, confidence, raw payload, and extractor version.
- **Error handling:** If a pipeline step fails, log the error, stream it to the frontend, and continue to the next step where possible. Don't let a failed PDF extraction kill the whole pipeline.

## Interfaces With Other Agents

- **Database agent** provides the schema. You query it via asyncpg or the Supabase client. Coordinate on enum values and view signatures.
- **Frontend agent** consumes your API endpoints. The SSE event format in `requirements.md` §4.3 is the contract — don't change the shape without coordinating.

## Reference Documents

- `architecture_er_pipeline.md` — full pipeline architecture, agent prompts, guardrails
- `requirements.md` — API spec, confidence formula, data derivation rules
- `data_model.md` — table schemas for write-back
