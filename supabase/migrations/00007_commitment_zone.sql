-- Commitment zone: Targets, Progress Snapshots, Decarbonization Programs

CREATE TABLE emissions_target (
  target_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id           UUID NOT NULL REFERENCES company(company_id),
  target_type          target_type_enum NOT NULL,
  sbti_status          sbti_status_enum DEFAULT 'not_submitted',
  sbti_validation_date DATE,
  baseline_year        INT,
  target_year          INT,
  baseline_tco2e       DECIMAL,
  target_tco2e         DECIMAL,
  reduction_pct        DECIMAL,
  scope_coverage       TEXT[] DEFAULT '{}',
  is_absolute          BOOLEAN DEFAULT true,
  sub_category         sub_category_enum DEFAULT 'none',
  target_language      TEXT,
  set_on               DATE,
  last_verified_at     TIMESTAMPTZ,
  is_withdrawn         BOOLEAN NOT NULL DEFAULT false,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE target_progress_snapshot (
  snapshot_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  target_id                 UUID NOT NULL REFERENCES emissions_target(target_id),
  reporting_year            INT NOT NULL,
  current_tco2e             DECIMAL,
  pct_reduction_vs_baseline DECIMAL,
  pct_of_target_achieved    DECIMAL,
  on_track                  BOOLEAN,
  attribution_notes         TEXT,
  is_withdrawn              BOOLEAN NOT NULL DEFAULT false,
  created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE decarbonization_program (
  program_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id               UUID NOT NULL REFERENCES company(company_id),
  program_name             TEXT NOT NULL,
  lever_type               lever_type_enum NOT NULL,
  estimated_reduction_tco2e DECIMAL,
  target_year              INT,
  ghg_code_targeted        TEXT REFERENCES ghg_protocol_category(ghg_code),
  description              TEXT,
  started_on               DATE,
  last_reaffirmed_in_year  INT,
  status                   program_status_enum DEFAULT 'active',
  is_withdrawn             BOOLEAN NOT NULL DEFAULT false,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);
