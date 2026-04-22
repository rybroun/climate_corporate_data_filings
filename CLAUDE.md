# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

**Company Carbon Lookup** — a web application that lets users search any company (by name, URL, or Wikidata ID), resolves the entity, discovers sustainability documents from the public web, extracts structured climate data, and presents a verified carbon footprint with cited sources.

## Project Structure

```
├── data_model.md                          # Canonical data model spec (ER diagram, table reference, reconciliation logic)
├── architecture_er_pipeline.md            # ER + ingestion pipeline architecture
├── requirements.md                        # Frontend + API requirements spec
├── agents/                                # Agent role definitions for parallel development
├── design_handoff_company_carbon_lookup/   # High-fidelity HTML/CSS/JSX prototype (reference only, not production code)
│   ├── Company Carbon Lookup.html         # Entry point
│   ├── app.jsx                            # All React components + sample data fixtures
│   ├── styles.css                         # Design tokens + component styles
│   └── README.md                          # Design handoff documentation
└── sample_data/                           # Real sustainability PDFs for testing extraction
```

## Tech Stack

| Layer | Technology |
|---|---|
| Database | Supabase (Postgres + Storage) |
| Backend / API | FastAPI (Python) |
| Extraction | PyMuPDF + Claude API (tool use) |
| Agentic crawl | Claude Agent SDK |
| Web search | Serper API |
| Frontend | Next.js + React |

## Architecture — Key Concepts

### Data Model (see `data_model.md`)

Five logical zones: Identity (COMPANY), Emissions (DISCLOSURE → LINE_ITEM → CATEGORY_MAPPING → GHG_PROTOCOL_CATEGORY), Commitment (TARGET + PROGRESS + PROGRAM), Validation (CERTIFICATION), Source/Provenance (SOURCE_DOCUMENT + DATA_PROVENANCE).

**Critical pattern:** Multiple observations per fact, reconciled at query time via prioritized coalesce over `source_authority`. Never overwrite — both observations coexist. Implement canonical-metric coalesce as a DB view or helper function (`get_canonical_metric`), not per-screen.

### Entity Resolution (see `architecture_er_pipeline.md`)

- LLM normalizes user input but **preserves legal suffixes** (S.A., GmbH, PLC) as jurisdiction disambiguation signals
- Local DB lookup first (pg_trgm fuzzy match), then Wikidata as the single external identity source
- Reranker outputs are persisted for every ER query
- COMPANY rows populated only with what Wikidata provides; everything else comes from extraction

### Frontend (see `design_handoff_company_carbon_lookup/`)

Three-screen flow: **Home** (search + sample grid) → **Searching** (animated 7-step pipeline + worker log) → **Results** (emissions headline, scope breakdown, YoY trend, cited sources, confidence score).

Design is high-fidelity — recreate pixel-perfectly. Key tokens: `--forest` primary accent (oklch), Inter Tight headings, Inter body, JetBrains Mono for data/kickers. The prototype uses hardcoded `SAMPLES` and `EMISSIONS_DATA` — in production these come from API endpoints backed by the data model.

### Pipeline Flow

```
User search → ER (local + Wikidata) → Document Discovery (Claude Agent SDK + Serper)
→ PDF Extraction (PyMuPDF + Claude) → Category Mapping → Write-back → Results
```

All discovery and extraction happens on-the-fly per user request (no batch pre-population in v1). Progressive UI updates via SSE as pipeline steps complete.

## Development Agents

This project is developed by three parallel agents (see `agents/` for full definitions):

1. **Database Agent** — Supabase schema, migrations, pg_trgm indexes, views, storage buckets
2. **Backend Agent** — FastAPI API, ER pipeline, Claude Agent SDK document discovery, PyMuPDF extraction
3. **Frontend Agent** — Next.js app implementing the design handoff, SSE integration for pipeline progress

Agents share contracts via the requirements spec. The database agent should land first (schema), then backend + frontend can proceed in parallel.
