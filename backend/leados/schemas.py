from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class AssertionType(StrEnum):
    FACT = "FACT"
    ALLEGATION = "ALLEGATION"
    INFERENCE = "INFERENCE"
    COMMERCIAL_THESIS = "COMMERCIAL_THESIS"


class AuditStatus(StrEnum):
    VERIFIED = "VERIFIED"
    NEEDS_RESEARCH = "NEEDS_RESEARCH"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REJECTED = "REJECTED"


class HumanStatus(StrEnum):
    MONITOR = "MONITOR"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_RESEARCH = "NEEDS_RESEARCH"


class FeedbackStatus(StrEnum):
    NOT_RELEVANT = "Not Relevant"
    CONTACTED = "Contacted"
    NO_RESPONSE = "No Response"
    RESPONDED = "Responded"
    MEETING = "Meeting"
    PROPOSAL = "Proposal"
    ENGAGED = "Engaged"
    WON = "Won"
    LOST = "Lost"


class FeedbackReason(StrEnum):
    WRONG_COMPANY = "Wrong Company"
    WRONG_TIMING = "Wrong Timing"
    WRONG_SERVICE = "Wrong Service"
    NO_BUDGET = "No Budget"
    NO_RELATIONSHIP = "No Relationship"
    CONFLICT = "Conflict"
    EXISTING_COUNSEL = "Existing Counsel"
    NO_NEED = "No Need"
    OTHER = "Other"


class VerticalDefinition(Contract):
    id: str
    name: str
    description: str
    typical_client: list[str]
    typical_problem: str
    buyer_roles: list[str]
    services: list[str]
    deliverables: list[str]
    positive_signals: list[str]
    negative_signals: list[str]
    disqualifiers: list[str]
    follow_on_services: list[str]
    related_verticals: list[str]
    keywords: list[str]
    semantic_queries: list[str]
    default_signal_weights: dict[str, int]
    version: str


class SignalDefinition(Contract):
    signal_id: str
    name: str
    description: str
    vertical_ids: list[str]
    keywords: list[str]
    semantic_description: str
    base_strength: int = Field(ge=0, le=25)
    recency_decay: str
    source_reliability_requirement: float = Field(ge=0, le=1)
    possible_buyers: list[str]
    possible_services: list[str]
    disqualifiers: list[str]
    examples: list[str]
    version: str


class CompanyInput(Contract):
    name: str = Field(min_length=1, max_length=250)
    aliases: list[str] = []
    domain: str | None = None
    country: str
    sector: str
    employee_range: str
    funding_stage: str
    locations: list[str]
    description: str

    @field_validator("name", "country", "sector")
    @classmethod
    def nonblank_company_fields(cls, value):
        if not value.strip():
            raise ValueError("Company name, country and sector must be nonblank")
        return value.strip()


class MarketDocument(Contract):
    company: CompanyInput
    source_url: HttpUrl
    source_name: str
    source_type: str
    published_date: date | None
    snippet: str = Field(max_length=20000)
    confidence: float = Field(ge=0, le=1)
    assertion_type: AssertionType = AssertionType.FACT
    company_match: bool = True
    conflict: bool = False
    author: str | None = None
    jurisdiction: str | None = None
    language: str = "en"
    record_origin: str = "LEGACY_UNKNOWN"
    provenance: dict = Field(default_factory=dict)
    provider_score: float | None = None
    title: str = ""


class Evidence(Contract):
    id: str
    source_url: HttpUrl
    source_name: str
    source_type: str
    published_date: date | None
    retrieved_at: datetime
    snippet: str
    confidence: float = Field(ge=0, le=1)
    content_hash: str
    assertion_type: AssertionType
    company_match: bool
    conflict: bool
    author: str | None = None
    jurisdiction: str | None = None
    language: str


class Claim(Contract):
    type: AssertionType
    text: str
    evidence_ids: list[str]


class ResearchOutput(Contract):
    inferences: list[Claim]
    commercial_thesis: str
    why_now: str
    outreach_angle: str
    need: float = Field(ge=0, le=1)
    mandate_value: float = Field(ge=0, le=1)

    @field_validator("inferences")
    @classmethod
    def inference_types(cls, claims):
        if any(claim.type != AssertionType.INFERENCE for claim in claims):
            raise ValueError("Research interpretations must be labelled INFERENCE")
        return claims


class ScorePart(Contract):
    points: int = Field(ge=0)
    maximum: int = Field(ge=0)
    rationale: str


class OpportunityOutput(Contract):
    record_origin: str = "LEGACY_UNKNOWN"
    qualification: dict = Field(default_factory=dict)
    score_inputs: dict = Field(default_factory=dict)
    id: str
    company_id: str
    company: str
    sector: str
    country: str
    location: str
    vertical_id: str
    vertical_name: str
    opportunity_type: str
    trigger: str
    trigger_date: date | None
    age_days: int | None
    facts: list[Claim]
    allegations: list[Claim]
    inferences: list[Claim]
    commercial_thesis: str
    evidence: list[Evidence]
    novation_service: str
    why_now: str
    decision_maker_roles: list[str]
    score_components: dict[str, ScorePart]
    score: int = Field(ge=0, le=100)
    score_band: str
    confidence: float = Field(ge=0, le=1)
    audit_status: AuditStatus
    audit_reasons: list[str]
    recommended_action: str
    outreach_angle: str
    human_status: HumanStatus
    score_version: str
    knowledge_version: str
    signal_version: str
    created_at: datetime
    updated_at: datetime
    draft: dict | None
    reviews: list[dict]
    feedback: list[dict]
    contact_history: list[dict]
    suppressed: bool
    suppression_flags: dict[str, bool]
    email_send_enabled: bool = False


class ReviewInput(Contract):
    reviewer: str = Field(min_length=1, max_length=150)
    notes: str = Field(default="", max_length=5000)

    @field_validator("reviewer")
    @classmethod
    def named_reviewer(cls, reviewer):
        if not reviewer.strip():
            raise ValueError("Reviewer name is required")
        return reviewer.strip()


class FeedbackInput(Contract):
    status: FeedbackStatus
    reason: FeedbackReason | None = None
    notes: str = Field(default="", max_length=5000)
    buyer_role: str | None = Field(default=None, max_length=150)


class RunInput(Contract):
    company: str | None = Field(default=None, max_length=250)


class CompanyRunInput(Contract):
    company: str = Field(min_length=1, max_length=250)


class SuppressionInput(Contract):
    do_not_contact: bool = False
    opted_out: bool = False
    bounced: bool = False
    reason: str = Field(default="", max_length=2000)


class ExaSearchInput(Contract):
    company: str | None = Field(default=None, max_length=250)
    num_results: int | None = Field(default=None, ge=1, le=100)


class ExaAgentInput(Contract):
    query: str = Field(min_length=3, max_length=1000)
    effort: str = Field(default="auto")


class LiveDiscoveryInput(Contract):
    cache_only: bool = False
    query_offset: int = Field(default=0, ge=0, le=10000)
    verticals: list[str] | None = None
    max_queries: int | None = Field(default=None, ge=1, le=100)
    max_companies: int | None = Field(default=None, ge=1, le=500)
    dry_run: bool | None = None
    company: str | None = Field(default=None, max_length=250)
