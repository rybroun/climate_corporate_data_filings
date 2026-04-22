# Entity Resolution & Data Ingestion Pipeline — Architecture Approach

## What this document covers

End-to-end design for: **user provides a company name or Wikidata QID → system resolves the entity, discovers sustainability documents, extracts structured climate data, and writes it into the data model.**

This is the "cold start" path — the company may not exist in our database yet.

---

## 1. The user-facing flow

```
User input (free text or Wikidata QID)
        │
        ▼
┌─────────────────┐
│  Entity          │
│  Resolution      │──── Match found ──── Show existing data
│  (ER)            │
└────────┬────────┘
         │ No match / partial match
         ▼
┌─────────────────┐
│  Identity        │
│  Enrichment      │──── Create/update COMPANY row
│  (external APIs) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Document        │
│  Discovery       │──── Find PDFs on the web
│  (agentic crawl) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Extraction      │
│  Pipeline        │──── Parse docs → structured data
│  (LLM + parsers) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Write-back      │
│  & Reconciliation│──── Populate all data model tables
└─────────────────┘
```

The user sees: a search bar, a disambiguation step if needed, then a company profile that fills in progressively as the pipeline runs.

---

## 2. Entity Resolution (ER)

### 2.1 Input normalization

An LLM interprets and normalizes the raw user input, but **preserves all metadata** — nothing is thrown away. Legal suffixes are particularly valuable for country-level disambiguation during ER (e.g., "S.A." suggests France/Spain/Brazil, "GmbH" confirms Germany, "PLC" confirms UK/Ireland).

The LLM normalization step produces a structured object:

```json
{
  "normalized_name": "Danone",
  "legal_suffix": "S.A.",
  "inferred_jurisdiction": "FR",
  "original_input": "Danone S.A.",
  "input_type": "company_name",
  "confidence": 0.95
}
```

- The `legal_suffix` and `inferred_jurisdiction` are carried forward as **soft signals** into local matching and Wikidata search — they narrow candidates but don't hard-filter (a user typing "Danone GmbH" might mean the German subsidiary or might just be wrong about the suffix).
- Unicode normalization (NFC), case-fold, collapse whitespace still happen deterministically.
- If the input is a Wikidata QID (`Q####`), route directly to the Wikidata entity lookup — skip fuzzy matching entirely.

### 2.2 Local lookup (fast path)

Query the COMPANY table first. This avoids external API calls when we already have the entity.

**Search strategy — ordered by precision:**

1. **Exact match on Wikidata QID**: If user provided a QID, match on `wikidata_qid` field directly.
2. **Exact match on canonical_name or legal_name**: Case-insensitive.
3. **Alias array search**: `WHERE $input = ANY(aliases)` — case-insensitive.
4. **Fuzzy match**: Trigram similarity (`pg_trgm`) on `canonical_name`, `legal_name`, and unnested `aliases`. Threshold at 0.4 similarity, return top 5 candidates. When `inferred_jurisdiction` is available from 2.1, boost candidates matching that country.

**Postgres support needed:** `pg_trgm` extension for trigram similarity. Index: `GIN(canonical_name gin_trgm_ops)`, same for `legal_name`. For the alias array, a GIN index on the array or a trigram index on `unnest(aliases)` via a generated column or materialized view.

**Reranker outputs:** Every local lookup produces a ranked candidate list with similarity scores and match signals. These reranker outputs (candidate IDs, scores, match type, signals used) must be persisted — they feed the confidence score shown in the UI and are essential for debugging ER quality over time. Table design TBD when we build out the schema, but the contract is: every ER query produces a stored reranker result, even for single high-confidence matches.

**Result states:**
- **Single high-confidence match** (similarity > 0.85): Auto-resolve, skip disambiguation.
- **Multiple candidates** (0.4–0.85): Present disambiguation UI to user. Show canonical_name, hq_country, industry to help them pick.
- **No match**: Proceed to external lookup.

### 2.3 External lookup (cold start)

When local lookup fails, query **Wikidata** as the single external identity source. Free, no API key, no rate limits, and strong coverage of the large companies that publish sustainability reports.

| Source | What it gives us | API | Rate limits |
|---|---|---|---|
| **Wikidata** | Legal name, aliases, ticker, LEI, HQ country, parent company, official website, industry (NAICS/ISIC), inception date | REST API (`wbsearchentities`) + SPARQL endpoint | Free, no key needed, generous limits |

**Search strategy:**
- If user provided a Wikidata QID → direct entity lookup via `wikidata.org/wiki/Special:EntityData/{QID}.json`, single result.
- Otherwise → search by `normalized_name` via `wbsearchentities` API (`action=wbsearchentities&search={name}&type=item&language=en&limit=10`). Filter results to entities with `P31` (instance of) = company/business/organization.
- If `inferred_jurisdiction` is available from 2.1 (via legal suffix), boost candidates whose `P17` (country) or `P159` (HQ location) matches.
- Take the top 5 and run them through the same reranker as local lookup (see 2.2) — persist the reranker outputs.
- **Single high-confidence match** → auto-resolve. **Multiple plausible candidates** → present disambiguation UI. **No results** → flag for manual entry.

**Wikidata properties we extract:**

| Property | Wikidata PID | Maps to COMPANY field |
|---|---|---|
| Official name | `P1448` | `legal_name` |
| Also known as | aliases | `aliases` |
| Country | `P17` | `hq_country` |
| Stock exchange ticker | `P414` + `P249` | `ticker` |
| LEI | `P1278` | `lei` |
| Official website | `P856` | used for document discovery |
| Parent organization | `P749` | `parent_company_id` (if parent already in DB) |
| Industry | `P452` | `industry_naics` (via crosswalk) |
| Inception | `P571` | informational |

### 2.4 COMPANY row creation

Once resolved (either by user disambiguation or auto-match), upsert into COMPANY using whatever Wikidata provides:

```
canonical_name       ← Wikidata label (or existing DB name if updating)
legal_name           ← P1448 official name (if available)
aliases              ← merge: user's original input + Wikidata aliases + any prior aliases
wikidata_qid         ← QID (e.g., Q183)
ticker               ← P414/P249 stock exchange + ticker symbol
lei                  ← P1278 LEI code
hq_country           ← P17 country → ISO 3166-1 alpha-2
industry_naics       ← P452 industry (crosswalk to NAICS if needed)
is_public            ← true if ticker exists
```

All other fields (`employee_count`, `annual_revenue_eur`, governance fields) remain NULL at this stage — they come from the extraction pipeline when we parse actual sustainability documents.

The principle: **at ER time, populate only what Wikidata gives us.** Don't synthesize or infer beyond what the registry provides. Wikidata is rich for our use case — we get ticker, LEI, and official website at ER time, not just legal name and jurisdiction.

### 2.5 Subsidiary resolution

When we ingest a subsidiary list document (like the Danone Subsidiaries 2024 PDF), we need to resolve each subsidiary entity too. This is a batch ER problem:

- Extract subsidiary names + jurisdictions from the document (see extraction pipeline)
- For each, run the local lookup → external lookup → create flow
- Set `parent_company_id` to the parent company
- This can produce hundreds of COMPANY rows (Danone has ~230 subsidiaries)

**Important:** Subsidiary ER should be a background job, not blocking the user flow. The parent company profile can show "230 subsidiaries identified, resolution in progress."

---

## 3. Document Discovery (Agentic Crawl)

### 3.1 The problem

Given a resolved COMPANY, find the sustainability-relevant documents that exist on the public web. These are the source documents that will feed the extraction pipeline.

The challenge: there's no single URL pattern. Danone publishes at `danone.com/integrated-annual-report.html`. Mondelez puts CDP responses on `cdp.net`. SBTi commitments live on `sciencebasedtargets.org`. Some companies put everything in an investor relations subdirectory, others have a dedicated sustainability microsite.

### 3.2 Discovery strategy — all on-the-fly

For v1, **all document discovery happens on-the-fly** as part of the per-company pipeline triggered by the user's search. No pre-populated batch jobs. The agent discovers, downloads, and hands off to extraction in a single run.

> **Future:** Structured API ingestion (CDP bulk download, SBTi database export, B Corp directory) and regulatory filing monitors (CSRD, SEC, SB 253) should move to scheduled batch jobs so we have data before users ask for it. But for now, the agentic crawl is the only discovery path.

**The discovery agent checks all source types in a single pass:**

1. **Company website crawl.** Start from the company's official website (from Wikidata `P856` or a Serper search). The agent identifies the sustainability/ESG/CSR section by:
   - Checking common paths: `/sustainability`, `/esg`, `/csr`, `/responsibility`, `/impact`, `/investor-relations`
   - Parsing the site navigation/footer for sustainability-related links
   - Falling back to a Serper search: `site:danone.com sustainability report filetype:pdf`

2. **Structured source lookup.** In the same agent run, also search for:
   - CDP responses: Serper search `"{company name}" CDP climate change response filetype:pdf`
   - SBTi commitments: Serper search `site:sciencebasedtargets.org "{company name}"`
   - B Corp: Serper search `site:bcorporation.net "{company name}"`

3. **Identify downloadable documents.** Across all results, find links to PDFs. Classify each by `source_type` using the link text, URL, and page context:
   - "Annual Report" / "Integrated Annual Report" → `annual_report` / `integrated_report`
   - "CDP" → `cdp_response`
   - "Climate Transition Plan" / "Climate Action Plan" → `transition_plan`
   - "Non-Financial Statement" / "DPEF" / "NFRD" → `non_financial_statement`
   - "Universal Registration Document" → `annual_report`
   - "Sustainability Report" / "ESG Report" / "Impact Report" → `impact_report`

4. **Download and deduplicate.** For each PDF:
   - Download to temp storage
   - Compute SHA-256 `content_hash`
   - Check if `SOURCE_DOCUMENT` already has this hash → skip if duplicate
   - Upload to Supabase Storage at the deterministic path
   - Create `SOURCE_DOCUMENT` row

### 3.3 Agent architecture for Tier 2

**Technology choice:** This is a good fit for an LLM-driven agent with tool use, not a traditional web scraper. The agent needs to reason about navigation structure, classify documents by type, and handle the long tail of website layouts.

**Recommended stack:**

- **Orchestrator:** Claude Agent SDK
- **Tools available to the agent:**
  - `web_search(query)` — Serper API for `site:{domain} sustainability report filetype:pdf`
  - `fetch_page(url)` → returns rendered HTML (use a headless browser like Playwright for JS-rendered pages)
  - `extract_links(html, filter)` → parse links matching patterns (PDF hrefs, sustainability-related anchor text)
  - `download_pdf(url)` → download, hash, return metadata
  - `classify_document(url, link_text, page_context)` → LLM call to determine `source_type`
  - `check_existing(content_hash)` → DB lookup for deduplication

**Agent prompt (simplified):**
```
You are a document discovery agent. Given a company name and website URL,
find all publicly available sustainability/climate disclosure PDFs.

Look for: annual/integrated reports, CDP responses, climate transition plans,
non-financial statements, sustainability reports.

For each document found, call download_pdf and classify_document.
Stop when you have checked all reasonable locations on the site.
```

**Guardrails:**
- Max 50 page fetches per company (prevent runaway crawling)
- Stay within the company's domain (no following external links except known registries)
- Respect robots.txt
- Rate limit: max 2 concurrent requests per domain, 1-second delay between requests
- Timeout: 5 minutes per company discovery session

### 3.4 Discovery state machine

```
PENDING → CRAWLING → DOCUMENTS_FOUND → DONE
                  ↘ NO_DOCUMENTS → DONE (flag for manual review)
                  ↘ ERROR → RETRY (max 2) → FAILED
```

Track discovery runs so we know when a company was last crawled and can schedule re-crawls (e.g., annually after typical publication dates).

---

## 4. Extraction Pipeline

### 4.1 The problem

Given a source document (PDF), extract structured data that maps to the data model tables: disclosures, line items, targets, programs, certifications, governance signals, and subsidiary lists.

### 4.2 Extraction approach: two-phase

**Phase 1: PDF → text + tables (deterministic)**

Use **PyMuPDF (fitz)** for all PDF parsing — it handles text extraction, table detection, and page-level chunking in a single dependency with no external services. Fast, well-maintained, and sufficient for the document types we're handling (corporate sustainability reports are overwhelmingly born-digital PDFs, not scans).

Output of Phase 1: a structured representation per page — `{ page_number, text_blocks[], tables[] }`.

**Phase 2: Structured content → data model rows (LLM)**

Send page-level chunks to Claude with a structured output schema. Use tool use / function calling to get typed outputs.

**Key design decision: extraction is per-table, not monolithic.** Run separate, focused extraction passes:

| Pass | Input focus | Output table(s) | Why separate |
|---|---|---|---|
| **Emissions pass** | Emissions summary tables, Scope 1/2/3 sections | `EMISSIONS_DISCLOSURE` + `EMISSIONS_LINE_ITEM` | These are the densest numerical tables; focused context improves accuracy |
| **Targets pass** | Target/commitment sections, SBTi references | `EMISSIONS_TARGET` | Different page locations, different schema |
| **Programs pass** | Strategy/action plan sections | `DECARBONIZATION_PROGRAM` | Narrative-heavy, needs different prompt tuning |
| **Governance pass** | Governance section, compensation tables | `COMPANY` governance fields | Small fixed schema, different part of document |
| **Certifications pass** | Ratings/scores sections, external validation | `SUSTAINABILITY_CERTIFICATION` | Scattered across document |
| **Subsidiary pass** | Subsidiary list appendix (often a separate document) | `COMPANY` rows (children) | Tabular extraction, batch ER needed |

Each pass gets:
- The relevant pages (identified by a lightweight page-classification step first)
- A pass-specific system prompt with the target schema
- Few-shot examples from the Danone worked example in the data model

**Page classification step (runs first):**
Send the full table of contents / page headers to the LLM and ask: "Which pages contain emissions data? Target commitments? Governance information?" This produces a page routing map so each extraction pass only sees relevant pages.

### 4.3 Extraction output format

Each extraction pass returns structured JSON matching the data model schema. Example for the emissions pass:

```json
{
  "disclosure": {
    "reporting_year": 2023,
    "scope_1_tco2e": 564000,
    "scope_2_location_tco2e": 312000,
    "scope_2_market_tco2e": 198000,
    "scope_3_total_tco2e": 24100000,
    "methodology": "ghg_protocol_corporate",
    "verification_status": "limited_assurance",
    "verifier_name": "PwC",
    "boundary_definition": "Operational control",
    "page_number": 47,
    "section_reference": "Table 4.2"
  },
  "line_items": [
    {
      "native_category": "Purchased goods and services - Milk",
      "tco2e": 7900000,
      "data_quality_tier": "supplier_specific",
      "tags": ["flag"]
    }
  ],
  "confidence": 0.92,
  "extraction_notes": "Scope 2 market-based inferred from REC disclosure on p.48"
}
```

### 4.4 Category mapping (native → GHG Protocol)

After extracting line items with `native_category`, we need `COMPANY_CATEGORY_MAPPING` rows. This is a separate LLM step:

1. Collect all unique `native_category` values for the company
2. Present them alongside the GHG Protocol category reference table
3. Ask the LLM to produce mappings with `allocation_pct` and `rationale`
4. Flag any ambiguous mappings (confidence < 0.8) for human review

This only needs to run once per company (or when they change their category taxonomy). The `effective_from_year` / `effective_to_year` fields handle versioning.

### 4.5 Confidence scoring and human review routing

Every extraction produces a `DATA_PROVENANCE` row with:
- `confidence`: LLM self-reported confidence (calibrated via few-shot examples)
- `extraction_method`: `llm_structured` for the main path
- `raw_extraction_payload`: the full LLM response JSON
- `human_verified`: `false` initially

**Review routing rules:**
- confidence < 0.7 → queue for human review before the data goes live
- confidence 0.7–0.9 → data goes live, flagged for spot-check
- confidence > 0.9 → data goes live, no flag

### 4.6 Handling the specific document types in sample_data

| Document | Key extractions | Challenges |
|---|---|---|
| **Danone IAR 2024** (14MB, integrated annual report) | Emissions disclosure, line items, targets, programs, governance, certifications | Large doc, need page routing. Emissions tables may span multiple pages. |
| **Danone Climate Transition Plan 2023** | Decarbonization programs, target details, program timelines | Narrative-heavy, less tabular. Programs described in prose. |
| **Danone Subsidiaries 2024** | Subsidiary list → batch COMPANY creation | Tabular extraction. ~230 rows. Need to ER each subsidiary. |
| **Non-Financial Statement 2024** | Emissions disclosure (regulatory filing), governance | CSRD/DPEF format — `source_authority = regulatory_filing`. May duplicate IAR data. |
| **Creating Shared Value Sustainability Report 2023** (Nestle) | Full extraction for a different company | Tests the pipeline's generalization beyond Danone |
| **Mondelez CDP Response 2024** | CDP-structured disclosure, targets, Scope 3 detail | Semi-structured questionnaire format — more predictable layout |

---

## 5. Write-back & Reconciliation

### 5.1 Write order

Tables must be populated in dependency order:

```
1. COMPANY (if new)
2. SOURCE_DOCUMENT (the ingested PDF)
3. EMISSIONS_DISCLOSURE (references company + source doc)
4. EMISSIONS_LINE_ITEM (references disclosure + company)
5. COMPANY_CATEGORY_MAPPING (references company + GHG_PROTOCOL_CATEGORY)
6. EMISSIONS_TARGET (references company)
7. TARGET_PROGRESS_SNAPSHOT (references target)
8. DECARBONIZATION_PROGRAM (references company, optionally GHG category)
9. SUSTAINABILITY_CERTIFICATION (references company)
10. DATA_PROVENANCE (references source doc + any record from above)
```

Steps 3–9 can largely run in parallel since they only depend on steps 1–2.

### 5.2 Idempotency

Re-running extraction on the same document should not create duplicates. Dedup keys:

| Table | Natural key for dedup |
|---|---|
| `SOURCE_DOCUMENT` | `content_hash` (UNIQUE constraint) |
| `EMISSIONS_DISCLOSURE` | `(company_id, source_document_id, reporting_year)` |
| `EMISSIONS_LINE_ITEM` | `(disclosure_id, native_category)` |
| `EMISSIONS_TARGET` | `(company_id, target_type, baseline_year, target_year, scope_coverage)` |
| `COMPANY_CATEGORY_MAPPING` | `(company_id, native_category, ghg_code, effective_from_year)` |

Use `INSERT ... ON CONFLICT DO UPDATE` for upsert semantics.

### 5.3 Reconciliation on write

When a new disclosure is written for a (company, year) that already has rows, the system does **not** overwrite. Both observations coexist. The `source_authority` + `published_on` fields drive query-time reconciliation per the data model's coalesce pattern.

The write-back step should:
1. Check if existing disclosures exist for the same (company, year)
2. If yes, log that this is an additional observation (not a replacement)
3. Set `restated_from_prior = true` if the new source explicitly mentions restatement
4. Set `source_authority` based on the document type and verification status

---

## 6. Technology Stack

| Layer | Technology | Why |
|---|---|---|
| **Database** | Supabase (Postgres) | Already implied by data model (Supabase Storage for blobs). `pg_trgm` for fuzzy matching. Row-level security for multi-tenancy later. |
| **Backend / API** | **FastAPI** (Python) | Single language for API + extraction pipeline + agentic crawl. Async-native, great for streaming pipeline status to the frontend via SSE. |
| **Extraction pipeline** | Python + PyMuPDF + Claude API (tool use) | PyMuPDF for PDF parsing, Claude for structured extraction with tool use for typed outputs. |
| **Agentic crawl** | **Claude Agent SDK** (Python) | Agent with tool use for document discovery. Tools: web search, page fetch, PDF download, document classification. |
| **Web search** | **Serper API** | For `site:{domain} sustainability report filetype:pdf` queries. Simple REST API, fast, cheap. |
| **Headless browser** | Playwright (Python) | Some sustainability pages are JS-rendered SPAs |
| **Blob storage** | Supabase Storage | Already in the data model. S3-compatible API. |
| **Job queue** | Inngest or Trigger.dev | Document discovery + extraction are async jobs. Need retry, timeout, progress tracking. |
| **Frontend** | Next.js + React | Search bar, disambiguation UI, company profile with progressive loading |

---

## 7. Pipeline Orchestration

### 7.1 Job graph for a new company lookup

```
[user_search]
     │
     ▼
[entity_resolution]  ←── local DB + external APIs
     │
     ├── match found ──→ [check_freshness] ──→ [return_existing] or [re_crawl]
     │
     └── no match ──→ [create_company]
                           │
                           ▼
                    [document_discovery]  ←── agentic crawl
                           │
                    ┌──────┼──────┐
                    ▼      ▼      ▼
               [extract   [extract   [extract    ←── parallel per document
                doc_1]     doc_2]     doc_3]
                    │      │      │
                    └──────┼──────┘
                           ▼
                    [category_mapping]  ←── once per company, after all line items
                           │
                           ▼
                    [write_back]
                           │
                           ▼
                    [notify_user]  ←── "Danone profile ready — 6 documents, 4 years of data"
```

### 7.2 Progressive UI updates

The pipeline takes minutes, not milliseconds. The frontend should show progressive results:

1. **Immediate** (< 1s): ER result — "Found: Danone S.A. (FR)" with basic COMPANY fields
2. **Fast** (5–15s): Document discovery complete — "Found 6 documents" with list
3. **Progressive** (30s–3min): Extraction results stream in per-document — disclosure cards appear as each doc is processed
4. **Complete**: All extractions done, category mappings applied, full profile available

Use Supabase Realtime (Postgres LISTEN/NOTIFY) or SSE from the backend to push updates to the frontend.

---

## 8. Open Questions for Discussion

1. **Crawl scheduling**: How often should we re-crawl company websites? Annual reports drop once a year, but CDP responses have a specific disclosure cycle. Do we want event-driven triggers (e.g., monitor the CDP disclosure site for new submissions)?

2. **Manual upload vs. crawl-only**: Should users be able to upload PDFs directly (bypassing document discovery)? This is simpler for v1 and handles cases where documents are behind paywalls or login walls.

3. **Extraction accuracy bar**: What confidence threshold warrants blocking data from going live? 0.7 is a starting point but needs calibration against ground truth (e.g., the Danone worked example).

4. **Rate of new companies**: Is this primarily a "look up a few key suppliers" tool (tens of companies) or a "ingest entire supply chain" tool (thousands)? This changes whether the agentic crawl needs to be highly parallelized or can run serially.

5. **CDP data access**: Do we have (or plan to get) paid CDP API access? If yes, Tier 1 structured ingestion covers a huge chunk of the data. If not, we're relying on publicly available CDP response PDFs, which are less common.

6. **Multi-tenancy**: Does each user/customer see their own set of companies, or is this a shared database where any resolved company is visible to all? Affects whether COMPANY rows are shared or scoped.

7. **Human review workflow**: Where does the human reviewer work? A separate admin UI? Inline in the company profile? This affects how `DATA_PROVENANCE.human_verified` gets flipped.

8. **Reranker storage schema**: We've committed to persisting reranker outputs from ER (2.2). Need to design the table — likely something like `ER_MATCH_LOG(query_id, candidate_company_id, score, match_type, signals_json, chosen, created_at)`. Flesh this out during schema build-out.
