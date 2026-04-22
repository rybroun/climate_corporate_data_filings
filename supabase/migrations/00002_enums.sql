-- All Postgres enum types, defined before any table references them

CREATE TYPE benefit_corp_status_enum AS ENUM (
  'none', 'b_corp_certified', 'societe_a_mission', 'delaware_pbc', 'other'
);

CREATE TYPE methodology_enum AS ENUM (
  'ghg_protocol_corporate', 'iso_14064', 'tcfd_aligned', 'other'
);

CREATE TYPE verification_status_enum AS ENUM (
  'none', 'limited_assurance', 'reasonable_assurance'
);

CREATE TYPE source_authority_enum AS ENUM (
  'self_reported_verified', 'self_reported', 'regulatory_filing', 'third_party_estimated'
);

CREATE TYPE data_quality_tier_enum AS ENUM (
  'supplier_specific', 'hybrid', 'industry_average', 'spend_based'
);

CREATE TYPE target_type_enum AS ENUM (
  'near_term', 'long_term', 'net_zero', 'interim', 'sub_target'
);

CREATE TYPE sbti_status_enum AS ENUM (
  'not_submitted', 'committed', 'targets_set', 'validated', 'removed'
);

CREATE TYPE sub_category_enum AS ENUM (
  'methane', 'flag', 'energy', 'other', 'none'
);

CREATE TYPE lever_type_enum AS ENUM (
  'renewable_energy', 'fleet_electrification', 'supplier_engagement',
  'product_reformulation', 'regenerative_agriculture', 'packaging_redesign',
  'logistics_optimization', 'process_improvement', 'other'
);

CREATE TYPE program_status_enum AS ENUM (
  'active', 'completed', 'paused', 'abandoned'
);

CREATE TYPE certification_scheme_enum AS ENUM (
  'cdp_climate', 'cdp_water', 'cdp_forests', 'sbti', 'b_corp',
  're100', 'ep100', 'ev100', 'rspo', 'access_to_nutrition', 'other'
);

CREATE TYPE source_type_enum AS ENUM (
  'annual_report', 'integrated_report', 'cdp_response', 'transition_plan',
  'non_financial_statement', 'sbti_commitment', 'subsidiary_list',
  'impact_report', 'other'
);

CREATE TYPE extraction_method_enum AS ENUM (
  'llm_structured', 'llm_freeform', 'pdf_table_parser',
  'api_ingest', 'manual', 'human_reviewed'
);

CREATE TYPE er_source_enum AS ENUM (
  'local_db', 'wikidata'
);
