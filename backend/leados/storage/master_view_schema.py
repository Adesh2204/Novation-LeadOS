"""Presentation column names; technical workbook schemas are unchanged."""

MASTER_TAB = "LEADOS_MASTER_VIEW"
VISIBLE_COLUMNS = [
    "company",
    "industry",
    "country",
    "trigger",
    "trigger_date",
    "vertical",
    "recommended_service",
    "why_now",
    "score",
    "score_status",
    "confidence",
    "evidence_status",
    "source",
    "buyer",
    "review_status",
    "outreach_angle",
]
HELPER_COLUMNS = ["opportunity_id", "company_id", "primary_source_id", "updated_at"]
RESEARCH_COLUMNS = ["record_type", "research_status", "contact_status"]
MASTER_COLUMNS = VISIBLE_COLUMNS + HELPER_COLUMNS + RESEARCH_COLUMNS + ["row_id"]
