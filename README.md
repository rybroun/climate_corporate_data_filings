# Company Carbon Lookup

Search any company and get a verified carbon footprint derived from public data. The system resolves the entity, discovers sustainability documents from the public web, extracts structured emissions data, and presents results with full source citations.

## How it works

```
User searches "Danone S.A."
    → LLM normalizes input (preserves legal suffix for jurisdiction inference)
    → Local DB match (pg_trgm fuzzy search) or Wikidata fallback
    → Serper finds sustainability PDFs on the public web
    → PyMuPDF parses PDFs, Claude extracts structured emissions data
    → Data normalized to GHG Protocol, written to Supabase
    → Results displayed with scope breakdown, trend charts, and cited sources
```

The entire pipeline runs on-the-fly per request with real-time SSE streaming so users see each step as it completes.

## Architecture

| Layer | Technology |
|---|---|
| Database | Supabase (Postgres + Storage) |
| Backend | FastAPI (Python) |
| Extraction | PyMuPDF + Claude API (tool use) |
| Document discovery | Claude Agent SDK + Serper |
| Entity resolution | Wikidata (free, no API key) |
| Frontend | Next.js + React + TypeScript |

### Data model

14 Postgres tables organized into 5 zones:

- **Identity** — `company` with self-referential parent/subsidiary relationships
- **Emissions** — `emissions_disclosure` → `emissions_line_item` → `company_category_mapping` → `ghg_protocol_category` (normalization at query time, not on write)
- **Commitment** — `emissions_target` + `target_progress_snapshot` + `decarbonization_program`
- **Validation** — `sustainability_certification` (CDP, SBTi, B Corp, etc.)
- **Provenance** — `source_document` + `data_provenance` (every extracted value traceable to page + section)

Multiple observations per fact coexist and are reconciled at query time via a prioritized coalesce over `source_authority`.

### Pipeline steps

1. **Parse query** — LLM normalizes input, preserves legal suffix as jurisdiction signal
2. **Match entity** — local DB (pg_trgm) → Wikidata fallback → reranker outputs persisted
3. **Fetch public filings** — Serper web search + PDF download + Supabase Storage upload
4. **Extract emissions** — PyMuPDF parsing + Claude structured extraction (per-table passes)
5. **Normalize units** — convert to tCO₂e
6. **Classify Scope 1/2/3** — map native categories to GHG Protocol codes
7. **Store & cache** — write-back with upserts + DATA_PROVENANCE for every value

Known companies with existing data skip steps 3-7 and render instantly.

## Setup

### Prerequisites

- Python 3.10+
- Node.js 18+
- A Supabase project

### Environment variables

Copy `.env.example` and fill in your keys:

```bash
cp .env.example .env
```

Required:
- `SUPABASE_URL` — your Supabase project URL
- `SUPABASE_ANON_KEY` — Supabase anon/public key
- `SUPABASE_SERVICE_ROLE_KEY` — Supabase service role key
- `ANTHROPIC_API_KEY` — for LLM extraction and input parsing
- `SERPER_API_KEY` — for web search document discovery (free tier: 2,500/month at serper.dev)

### Database

Apply migrations to your Supabase project (via dashboard SQL editor or Supabase CLI):

```bash
# Files are in supabase/migrations/ — run in order (00001 through 00015)
```

### Backend

```bash
cd backend
pip install -e .
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000

## Project structure

```
├── backend/
│   └── app/
│       ├── api/            # FastAPI routes (search, resolve, company)
│       ├── models/         # Pydantic schemas + Python enums
│       ├── pipeline/       # 7-step pipeline (parse → match → fetch → extract → normalize → classify → store)
│       └── services/       # External integrations (Wikidata, Serper, PyMuPDF, Claude)
├── frontend/
│   └── src/
│       ├── app/            # Next.js pages (Home, Searching, Results)
│       ├── components/     # React components (SearchBar, PipelineCard, charts, etc.)
│       ├── hooks/          # useSSE hook for pipeline streaming
│       └── lib/            # API client, types, mock data, formatters
└── supabase/
    └── migrations/         # 15 ordered SQL migrations
```

## Design

The frontend implements a high-fidelity design with three screens:

- **Home** — search bar with live autocomplete, 7-step pipeline card, sample company grid
- **Searching** — animated pipeline with real-time worker log streaming via SSE
- **Results** — emissions headline (72px number), scope breakdown bars, YoY trend chart (stacked/line), cited sources with clickable PDF links

Design tokens: forest green accent (oklch), Inter Tight headings, Inter body, JetBrains Mono for data.
