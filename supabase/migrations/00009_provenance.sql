-- Provenance overlay: polymorphic pointers for any-row-to-source tracing

CREATE TABLE data_provenance (
  provenance_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  record_id            UUID NOT NULL,
  record_table         TEXT NOT NULL,
  source_document_id   UUID NOT NULL REFERENCES source_document(source_document_id),
  page_number          INT,
  section_reference    TEXT,
  extraction_date      DATE DEFAULT CURRENT_DATE,
  extraction_method    extraction_method_enum NOT NULL,
  extractor_version    TEXT,
  raw_extraction_payload JSONB,
  confidence           DECIMAL,  -- 0.0 to 1.0
  human_verified       BOOLEAN DEFAULT false,
  source_last_checked_at TIMESTAMPTZ,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
