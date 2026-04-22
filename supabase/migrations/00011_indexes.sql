-- Performance indexes

-- Entity resolution: trigram fuzzy matching
CREATE INDEX idx_company_canonical_trgm ON company USING GIN (canonical_name gin_trgm_ops);
CREATE INDEX idx_company_legal_trgm ON company USING GIN (legal_name gin_trgm_ops);
CREATE INDEX idx_company_aliases ON company USING GIN (aliases);
CREATE INDEX idx_company_wikidata ON company (wikidata_qid) WHERE wikidata_qid IS NOT NULL;

-- Emissions hot paths
CREATE INDEX idx_disclosure_company_year ON emissions_disclosure (company_id, reporting_year) WHERE NOT is_withdrawn;
CREATE INDEX idx_line_item_disclosure ON emissions_line_item (disclosure_id) WHERE NOT is_withdrawn;
CREATE INDEX idx_line_item_company ON emissions_line_item (company_id, reporting_year) WHERE NOT is_withdrawn;

-- Source document lookups
CREATE INDEX idx_source_doc_hash ON source_document (content_hash);
CREATE INDEX idx_source_doc_company ON source_document (company_id, source_type);

-- Provenance polymorphic lookups
CREATE INDEX idx_provenance_record ON data_provenance (record_table, record_id);
CREATE INDEX idx_provenance_source_doc ON data_provenance (source_document_id);

-- ER match log
CREATE INDEX idx_er_match_company ON er_match_log (chosen_company_id);
