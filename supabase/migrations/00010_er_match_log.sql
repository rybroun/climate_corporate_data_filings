-- ER support: reranker output persistence

CREATE TABLE er_match_log (
  query_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  raw_input         TEXT NOT NULL,
  normalized_input  JSONB,
  candidates        JSONB,  -- array of {company_id, score, match_type, signals}
  chosen_company_id UUID REFERENCES company(company_id),
  source            er_source_enum NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
