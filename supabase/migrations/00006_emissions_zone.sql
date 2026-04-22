-- Emissions zone: Disclosure, Line Items, Tags junction, Category Mapping

CREATE TABLE emissions_disclosure (
  disclosure_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id           UUID NOT NULL REFERENCES company(company_id),
  source_document_id   UUID NOT NULL REFERENCES source_document(source_document_id),
  reporting_year       INT NOT NULL,
  scope_1_tco2e        DECIMAL,
  scope_2_location_tco2e DECIMAL,
  scope_2_market_tco2e DECIMAL,
  scope_3_total_tco2e  DECIMAL,
  methodology          methodology_enum,
  verification_status  verification_status_enum DEFAULT 'none',
  verifier_name        TEXT,
  source_authority     source_authority_enum NOT NULL,
  boundary_definition  TEXT,
  boundary_notes       TEXT,
  restated_from_prior  BOOLEAN DEFAULT false,
  page_number          INT,
  section_reference    TEXT,
  published_on         DATE,
  last_verified_at     TIMESTAMPTZ,
  is_withdrawn         BOOLEAN NOT NULL DEFAULT false,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE (company_id, source_document_id, reporting_year)
);

CREATE TABLE emissions_line_item (
  line_item_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  disclosure_id        UUID NOT NULL REFERENCES emissions_disclosure(disclosure_id),
  company_id           UUID NOT NULL REFERENCES company(company_id),
  reporting_year       INT NOT NULL,
  native_category      TEXT NOT NULL,
  tco2e                DECIMAL NOT NULL,
  data_quality_tier    data_quality_tier_enum,
  is_excluded_from_target BOOLEAN DEFAULT false,
  exclusion_reason     TEXT,
  notes                TEXT,
  is_withdrawn         BOOLEAN NOT NULL DEFAULT false,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE (disclosure_id, native_category)
);

-- Junction table for line item tags (many-to-many)
CREATE TABLE emissions_line_item_tag (
  line_item_id UUID NOT NULL REFERENCES emissions_line_item(line_item_id) ON DELETE CASCADE,
  tag_code     TEXT NOT NULL REFERENCES emissions_category_tag(tag_code),
  PRIMARY KEY (line_item_id, tag_code)
);

CREATE TABLE company_category_mapping (
  mapping_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id          UUID NOT NULL REFERENCES company(company_id),
  native_category     TEXT NOT NULL,
  ghg_code            TEXT NOT NULL REFERENCES ghg_protocol_category(ghg_code),
  allocation_pct      DECIMAL NOT NULL DEFAULT 1.0,
  effective_from_year INT,
  effective_to_year   INT,
  rationale           TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE (company_id, native_category, ghg_code, effective_from_year)
);
