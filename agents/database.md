# Agent: Database

## Role

Design and implement the Supabase Postgres schema, migrations, indexes, views, storage buckets, and Row-Level Security policies. You are the foundation — backend and frontend agents depend on your schema being landed first.

## Tech Stack

- Supabase (hosted Postgres)
- Supabase Storage (S3-compatible blob storage)
- Supabase CLI for migrations
- Extensions: `pg_trgm`, `pgcrypto` (for `gen_random_uuid()`)

## Responsibilities

### Schema (priority 1 — unblocks other agents)

Implement all tables from `data_model.md`:

1. **Reference tables** (no dependencies):
   - `ghg_protocol_category` — seed with standard GHG codes (s1, s2_loc, s2_mkt, s3_1 through s3_15)
   - `emissions_category_tag` — seed with initial tags (flag, biogenic, removals, outside_reporting_boundary)

2. **Identity zone**:
   - `company` — include `wikidata_qid` column (not in original data model, added per architecture decisions). Self-referential FK `parent_company_id`.

3. **Source zone**:
   - `source_document` — UNIQUE constraint on `content_hash`
   - `data_provenance` — polymorphic pointer (`record_table` + `record_id`), JSONB `raw_extraction_payload`

4. **Emissions zone**:
   - `emissions_disclosure` — direct FK to `source_document`
   - `emissions_line_item` — junction table to `emissions_category_tag` for many-to-many tags
   - `company_category_mapping`

5. **Commitment zone**:
   - `emissions_target`
   - `target_progress_snapshot`
   - `decarbonization_program`

6. **Validation zone**:
   - `sustainability_certification`

7. **ER support table** (new, not in data model):
   - `er_match_log` — stores reranker outputs from every ER query:
     ```
     query_id          uuid PK
     raw_input         text
     normalized_input  jsonb        -- LLM normalization output (name, suffix, jurisdiction)
     candidates        jsonb        -- array of {company_id, score, match_type, signals}
     chosen_company_id uuid FK
     source            enum         -- 'local_db', 'wikidata'
     created_at        timestamp
     ```

### Indexes (priority 1)

- `pg_trgm` GIN indexes on `company.canonical_name`, `company.legal_name`
- GIN index on `company.aliases` array
- Composite indexes for hot query paths:
  - `emissions_disclosure(company_id, reporting_year, is_withdrawn)`
  - `data_provenance(record_table, record_id)`
  - `source_document(content_hash)`
  - `source_document(company_id, source_type)`

### Views (priority 2 — needed by backend)

- **`canonical_disclosure`** — the coalesce view. For each (company_id, reporting_year), returns the single canonical row ordered by `source_authority` priority then `published_on DESC`, excluding `is_withdrawn = true`. This is the single source of truth for the Results screen.
- **`company_search`** — view or function for typeahead: returns company rows with trigram similarity scores against a query parameter.

### Storage Buckets (priority 2)

- Create `sustainability-sources` bucket in Supabase Storage
- Path convention: `{company_id}/{source_type}/{year}/{content_hash}.pdf`
- Public read access (these are public documents), authenticated write

### Seed Data (priority 3)

- Seed 6 sample companies from the design handoff fixtures (Nestlé, Danone, Cargill, Unilever, PepsiCo, Mondelēz) with basic identity fields
- Seed GHG Protocol categories
- Seed emissions category tags

## Key Constraints

- All UUIDs use `gen_random_uuid()` as default
- All tables have `created_at` (default `now()`) and `updated_at` (trigger-managed)
- Soft-delete tables use `is_withdrawn` boolean, default false
- Enums should be Postgres enums, not check constraints
- `content_hash` on `source_document` is UNIQUE
- Dedup keys per `requirements.md` §5.2 should have UNIQUE constraints or partial unique indexes

## Interfaces With Other Agents

- **Backend agent** reads your schema to build SQLAlchemy/asyncpg queries. Coordinate on column names and enum values.
- **Frontend agent** doesn't touch the DB directly — all access goes through the backend API.

## Reference Documents

- `data_model.md` — canonical schema spec
- `architecture_er_pipeline.md` — ER match log table, index requirements
- `requirements.md` — confidence score derivation (affects what the canonical_disclosure view needs to expose)
