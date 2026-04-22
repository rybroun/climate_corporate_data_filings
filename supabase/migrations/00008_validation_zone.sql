-- Validation zone: Sustainability Certifications

CREATE TABLE sustainability_certification (
  certification_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id       UUID NOT NULL REFERENCES company(company_id),
  scheme           certification_scheme_enum NOT NULL,
  score_or_status  TEXT,
  year             INT,
  expires_on       DATE,
  scope_of_coverage TEXT,
  source_url       TEXT,
  last_verified_at TIMESTAMPTZ,
  is_withdrawn     BOOLEAN NOT NULL DEFAULT false,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
