-- Identity zone: Company table

CREATE TABLE company (
  company_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  canonical_name          TEXT NOT NULL,
  legal_name              TEXT,
  aliases                 TEXT[] DEFAULT '{}',
  parent_company_id       UUID REFERENCES company(company_id),
  wikidata_qid            TEXT,
  ticker                  TEXT,
  lei                     TEXT,
  hq_country              TEXT,  -- ISO 3166-1 alpha-2
  industry_naics          TEXT,
  is_public               BOOLEAN,
  employee_count          INT,
  annual_revenue_eur      DECIMAL,
  revenue_year            INT,
  exec_comp_tied_to_climate BOOLEAN,
  exec_comp_pct           DECIMAL,
  board_oversight          BOOLEAN,
  board_committee_name     TEXT,
  has_transition_plan      BOOLEAN,
  has_forest_policy        BOOLEAN,
  has_water_policy         BOOLEAN,
  has_human_rights_policy  BOOLEAN,
  benefit_corp_status      benefit_corp_status_enum DEFAULT 'none',
  last_policy_update       DATE,
  governance_last_verified_at TIMESTAMPTZ,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
