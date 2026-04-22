-- Source zone: Source Document table

CREATE TABLE source_document (
  source_document_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id         UUID NOT NULL REFERENCES company(company_id),
  content_hash       TEXT NOT NULL UNIQUE,
  storage_bucket     TEXT DEFAULT 'sustainability-sources',
  storage_path       TEXT,
  original_url       TEXT,
  source_type        source_type_enum NOT NULL,
  publication_date   DATE,
  retrieved_at       TIMESTAMPTZ DEFAULT now(),
  file_size_bytes    BIGINT,
  mime_type          TEXT DEFAULT 'application/pdf',
  page_count         INT,
  is_primary         BOOLEAN DEFAULT true,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
