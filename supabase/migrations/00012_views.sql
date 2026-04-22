-- Canonical disclosure view: coalesced best row per (company, year)
-- Priority: source_authority (verified > self > regulatory > estimated), then newest published_on

CREATE VIEW canonical_disclosure AS
SELECT DISTINCT ON (company_id, reporting_year)
  *
FROM emissions_disclosure
WHERE NOT is_withdrawn
ORDER BY
  company_id,
  reporting_year,
  CASE source_authority
    WHEN 'self_reported_verified' THEN 1
    WHEN 'regulatory_filing'     THEN 2
    WHEN 'self_reported'         THEN 3
    WHEN 'third_party_estimated' THEN 4
  END,
  published_on DESC NULLS LAST;


-- Company search function: trigram similarity with match scoring
CREATE OR REPLACE FUNCTION search_companies(query TEXT, max_results INT DEFAULT 5)
RETURNS TABLE(
  company_id UUID,
  canonical_name TEXT,
  legal_name TEXT,
  hq_country TEXT,
  ticker TEXT,
  wikidata_qid TEXT,
  similarity REAL,
  has_emissions_data BOOLEAN
)
LANGUAGE sql STABLE
AS $$
  SELECT
    c.company_id,
    c.canonical_name,
    c.legal_name,
    c.hq_country,
    c.ticker,
    c.wikidata_qid,
    GREATEST(
      similarity(c.canonical_name, query),
      COALESCE(similarity(c.legal_name, query), 0)
    ) AS similarity,
    EXISTS (
      SELECT 1 FROM emissions_disclosure ed
      WHERE ed.company_id = c.company_id AND NOT ed.is_withdrawn
    ) AS has_emissions_data
  FROM company c
  WHERE
    c.canonical_name % query
    OR c.legal_name % query
    OR query = ANY(c.aliases)
  ORDER BY similarity DESC
  LIMIT max_results;
$$;
