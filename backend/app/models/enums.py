"""
Python enums mirroring the Postgres enums from migration 00002_enums.sql.
Uses the (str, Enum) pattern so values serialize to strings in JSON responses.
"""

import enum


class BenefitCorpStatus(str, enum.Enum):
    NONE = "none"
    B_CORP_CERTIFIED = "b_corp_certified"
    SOCIETE_A_MISSION = "societe_a_mission"
    DELAWARE_PBC = "delaware_pbc"
    OTHER = "other"


class Methodology(str, enum.Enum):
    GHG_PROTOCOL_CORPORATE = "ghg_protocol_corporate"
    ISO_14064 = "iso_14064"
    TCFD_ALIGNED = "tcfd_aligned"
    OTHER = "other"


class VerificationStatus(str, enum.Enum):
    NONE = "none"
    LIMITED_ASSURANCE = "limited_assurance"
    REASONABLE_ASSURANCE = "reasonable_assurance"


class SourceAuthority(str, enum.Enum):
    SELF_REPORTED_VERIFIED = "self_reported_verified"
    SELF_REPORTED = "self_reported"
    REGULATORY_FILING = "regulatory_filing"
    THIRD_PARTY_ESTIMATED = "third_party_estimated"


class DataQualityTier(str, enum.Enum):
    SUPPLIER_SPECIFIC = "supplier_specific"
    HYBRID = "hybrid"
    INDUSTRY_AVERAGE = "industry_average"
    SPEND_BASED = "spend_based"


class TargetType(str, enum.Enum):
    NEAR_TERM = "near_term"
    LONG_TERM = "long_term"
    NET_ZERO = "net_zero"
    INTERIM = "interim"
    SUB_TARGET = "sub_target"


class SbtiStatus(str, enum.Enum):
    NOT_SUBMITTED = "not_submitted"
    COMMITTED = "committed"
    TARGETS_SET = "targets_set"
    VALIDATED = "validated"
    REMOVED = "removed"


class SubCategory(str, enum.Enum):
    METHANE = "methane"
    FLAG = "flag"
    ENERGY = "energy"
    OTHER = "other"
    NONE = "none"


class LeverType(str, enum.Enum):
    RENEWABLE_ENERGY = "renewable_energy"
    FLEET_ELECTRIFICATION = "fleet_electrification"
    SUPPLIER_ENGAGEMENT = "supplier_engagement"
    PRODUCT_REFORMULATION = "product_reformulation"
    REGENERATIVE_AGRICULTURE = "regenerative_agriculture"
    PACKAGING_REDESIGN = "packaging_redesign"
    LOGISTICS_OPTIMIZATION = "logistics_optimization"
    PROCESS_IMPROVEMENT = "process_improvement"
    OTHER = "other"


class ProgramStatus(str, enum.Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    PAUSED = "paused"
    ABANDONED = "abandoned"


class CertificationScheme(str, enum.Enum):
    CDP_CLIMATE = "cdp_climate"
    CDP_WATER = "cdp_water"
    CDP_FORESTS = "cdp_forests"
    SBTI = "sbti"
    B_CORP = "b_corp"
    RE100 = "re100"
    EP100 = "ep100"
    EV100 = "ev100"
    RSPO = "rspo"
    ACCESS_TO_NUTRITION = "access_to_nutrition"
    OTHER = "other"


class SourceType(str, enum.Enum):
    ANNUAL_REPORT = "annual_report"
    INTEGRATED_REPORT = "integrated_report"
    CDP_RESPONSE = "cdp_response"
    TRANSITION_PLAN = "transition_plan"
    NON_FINANCIAL_STATEMENT = "non_financial_statement"
    SBTI_COMMITMENT = "sbti_commitment"
    SUBSIDIARY_LIST = "subsidiary_list"
    IMPACT_REPORT = "impact_report"
    OTHER = "other"


class ExtractionMethod(str, enum.Enum):
    LLM_STRUCTURED = "llm_structured"
    LLM_FREEFORM = "llm_freeform"
    PDF_TABLE_PARSER = "pdf_table_parser"
    API_INGEST = "api_ingest"
    MANUAL = "manual"
    HUMAN_REVIEWED = "human_reviewed"


class ErSource(str, enum.Enum):
    LOCAL_DB = "local_db"
    WIKIDATA = "wikidata"
