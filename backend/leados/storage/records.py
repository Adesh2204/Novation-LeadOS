"""Typed domain records. No ORM, Google API or row-location dependency."""

from datetime import UTC, date, datetime
from typing import ClassVar, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def now():
    return datetime.now(UTC)


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    prefix: ClassVar[str] = "rec"
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=now)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value):
        if cls.__name__ not in {"Vertical", "Service"}:
            UUID(value[-36:])
        return value

    @model_validator(mode="after")
    def utc_dates(self):
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, datetime) and value.tzinfo is None:
                raise ValueError(f"{name} must include a UTC offset")
            if isinstance(value, datetime):
                object.__setattr__(self, name, value.astimezone(UTC))
        return self


class Company(Record):
    prefix: ClassVar[str] = "cmp"
    id: str = Field(default_factory=lambda: "cmp_" + str(uuid4()))
    identity_key: str
    canonical_name: str
    domain: str | None = None
    country: str
    sector: str
    employee_range: str
    funding_stage: str
    locations: list
    description: str
    merge_confidence: float = Field(default=1, ge=0, le=1)
    updated_at: datetime = Field(default_factory=now)
    website: str = ""
    linkedin_url: str = ""
    status: Literal["ACTIVE", "INACTIVE"] = "ACTIVE"
    last_seen_at: datetime = Field(default_factory=now)
    record_origin: Literal["LIVE", "MOCK", "LEGACY_UNKNOWN"] = "LEGACY_UNKNOWN"
    provenance: dict = Field(default_factory=dict)
    archived_at: datetime | None = None


class CompanyAlias(Record):
    prefix: ClassVar[str] = "als"
    id: str = Field(default_factory=lambda: "als_" + str(uuid4()))
    company_id: str
    name: str
    normalized_name: str
    country: str
    confidence: float = Field(ge=0, le=1)
    alias_domain: str = ""
    source: str = "resolution"


class Source(Record):
    prefix: ClassVar[str] = "pub"
    id: str = Field(default_factory=lambda: "pub_" + str(uuid4()))
    name: str
    source_type: str
    origin: str
    reliability: float = Field(ge=0, le=1)
    record_origin: Literal["LIVE", "MOCK", "LEGACY_UNKNOWN"] = "LEGACY_UNKNOWN"
    provenance: dict = Field(default_factory=dict)
    archived_at: datetime | None = None


class SourceDocument(Record):
    prefix: ClassVar[str] = "src"
    id: str = Field(default_factory=lambda: "src_" + str(uuid4()))
    source_id: str
    company_id: str
    source_url: str
    url_hash: str
    content_hash: str
    published_date: date | None = None
    retrieved_at: datetime = Field(default_factory=now)
    snippet: str
    confidence: float = Field(ge=0, le=1)
    assertion_type: Literal["FACT", "ALLEGATION", "INFERENCE", "COMMERCIAL_THESIS"]
    company_match: bool
    conflict: bool = False
    author: str | None = None
    jurisdiction: str | None = None
    language: str = "en"
    title: str = ""
    raw_text_reference: str = ""
    last_seen_at: datetime = Field(default_factory=now)
    record_origin: Literal["LIVE", "MOCK", "LEGACY_UNKNOWN"] = "LEGACY_UNKNOWN"
    provenance: dict = Field(default_factory=dict)
    archived_at: datetime | None = None
    content_history: list = Field(default_factory=list)

    @field_validator("source_url")
    @classmethod
    def valid_url(cls, value):
        from pydantic import HttpUrl, TypeAdapter

        return str(TypeAdapter(HttpUrl).validate_python(value))


class Vertical(Record):
    id: str
    version: str
    definition: dict


class Service(Record):
    id: str
    vertical_id: str
    name: str


class Signal(Record):
    id: str
    version: str
    definition: dict
    code: str


class CompanySignal(Record):
    prefix: ClassVar[str] = "csg"
    id: str = Field(default_factory=lambda: "csg_" + str(uuid4()))
    company_id: str
    signal_id: str
    event_date: date | None = None
    event_key: str
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list
    signal_key: str
    status: Literal["ACTIVE", "EXPIRED", "REJECTED", "DUPLICATE", "NEEDS_REVIEW"] = "ACTIVE"
    last_seen_at: datetime = Field(default_factory=now)
    detection_version: str = "1.0"
    record_origin: Literal["LIVE", "MOCK", "LEGACY_UNKNOWN"] = "LEGACY_UNKNOWN"
    provenance: dict = Field(default_factory=dict)
    archived_at: datetime | None = None
    qualification: dict = Field(default_factory=dict)


class Opportunity(Record):
    prefix: ClassVar[str] = "opp"
    id: str = Field(default_factory=lambda: "opp_" + str(uuid4()))
    company_id: str
    company_signal_id: str
    vertical_id: str
    service_id: str
    trigger: str
    trigger_date: date | None = None
    facts: list
    allegations: list
    inferences: list
    commercial_thesis: str
    why_now: str
    outreach_angle: str
    score: int = Field(ge=0, le=100, strict=True)
    score_band: Literal["HOT", "STRONG", "MONITOR", "IGNORE"]
    confidence: float = Field(ge=0, le=1)
    audit_status: Literal["VERIFIED", "NEEDS_RESEARCH", "INSUFFICIENT_EVIDENCE", "REJECTED"]
    audit_reasons: list
    human_status: Literal["PENDING_REVIEW", "APPROVED", "REJECTED", "NEEDS_RESEARCH", "MONITOR"] = (
        "PENDING_REVIEW"
    )
    score_version: str
    knowledge_version: str
    signal_version: str
    updated_at: datetime = Field(default_factory=now)
    opportunity_fingerprint: str = ""
    record_origin: Literal["LIVE", "MOCK", "LEGACY_UNKNOWN"] = "LEGACY_UNKNOWN"
    provenance: dict = Field(default_factory=dict)
    archived_at: datetime | None = None
    qualification: dict = Field(default_factory=dict)
    score_inputs: dict = Field(default_factory=dict)
    evaluation_history: list = Field(default_factory=list)

    @field_validator("facts", "allegations", "inferences")
    @classmethod
    def typed_claims(cls, values, info):
        from leados.schemas import Claim

        expected = {"facts": "FACT", "allegations": "ALLEGATION", "inferences": "INFERENCE"}[info.field_name]
        claims = [Claim.model_validate(v) for v in values]
        if any(c.type != expected for c in claims):
            raise ValueError("Assertion category does not match its field")
        return [c.model_dump(mode="json") for c in claims]


class OpportunityEvidence(Record):
    prefix: ClassVar[str] = "evi"
    id: str = Field(default_factory=lambda: "evi_" + str(uuid4()))
    opportunity_id: str
    document_id: str


class ScoreComponent(Record):
    prefix: ClassVar[str] = "sco"
    id: str = Field(default_factory=lambda: "sco_" + str(uuid4()))
    opportunity_id: str
    name: str
    points: int
    maximum: int
    rationale: str


class DecisionMakerRole(Record):
    prefix: ClassVar[str] = "buy"
    id: str = Field(default_factory=lambda: "buy_" + str(uuid4()))
    opportunity_id: str
    role: str
    rationale: str
    person_name: str = ""
    contact_status: str = "ROLE_ONLY"
    contact_source: str = ""
    contact_email: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)


class OutreachDraft(Record):
    prefix: ClassVar[str] = "out"
    id: str = Field(default_factory=lambda: "out_" + str(uuid4()))
    opportunity_id: str
    subjects: list
    body: str
    verified_fact_ids: list
    generation_version: str = "1.0"
    human_approved: bool = False
    approved_by: str = ""
    approved_at: datetime | None = None
    send_status: Literal["DRAFT", "BLOCKED"] = "DRAFT"
    sent_at: datetime | None = None


class HumanReview(Record):
    prefix: ClassVar[str] = "rev"
    id: str = Field(default_factory=lambda: "rev_" + str(uuid4()))
    opportunity_id: str
    reviewer: str
    decision: Literal["PENDING_REVIEW", "APPROVED", "REJECTED", "NEEDS_RESEARCH", "MONITOR"]
    notes: str


class HumanReviewTask(Record):
    prefix: ClassVar[str] = "tsk"
    id: str = Field(default_factory=lambda: "tsk_" + str(uuid4()))
    opportunity_id: str
    status: str = "PENDING_REVIEW"
    reason: str


class FeedbackEvent(Record):
    prefix: ClassVar[str] = "fbk"
    id: str = Field(default_factory=lambda: "fbk_" + str(uuid4()))
    opportunity_id: str
    status: str
    reason: str | None = None
    notes: str
    buyer_role: str | None = None
    score_snapshot: int
    score_version: str
    knowledge_version: str
    signal_version: str
    recorded_by: str = "Local reviewer"

    @field_validator("status")
    @classmethod
    def valid_status(cls, value):
        if value not in {
            "Not Relevant",
            "Contacted",
            "No Response",
            "Responded",
            "Meeting",
            "Proposal",
            "Engaged",
            "Won",
            "Lost",
        }:
            raise ValueError("Invalid feedback status")
        return value

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, value):
        if value is not None and value not in {
            "Wrong Company",
            "Wrong Timing",
            "Wrong Service",
            "No Budget",
            "No Relationship",
            "Conflict",
            "Existing Counsel",
            "No Need",
            "Other",
        }:
            raise ValueError("Invalid feedback reason")
        return value


Stage = Literal[
    "start", "discovery", "normalise", "resolve", "detect", "route", "research", "score", "audit", "store"
]


class ProviderRun(Record):
    prefix: ClassVar[str] = "run"
    id: str = Field(default_factory=lambda: "run_" + str(uuid4()))
    provider: str
    model: str | None = None
    status: Literal["RUNNING", "COMPLETED", "PARTIAL", "FAILED"]
    stage: Stage
    state: dict
    metrics: dict
    duration_ms: int = 0
    error: str | None = None
    revision: int = 0
    completed_at: datetime | None = None


class AuditLog(Record):
    prefix: ClassVar[str] = "aud"
    id: str = Field(default_factory=lambda: "aud_" + str(uuid4()))
    module: str
    input_ref: str | None = None
    output_ref: str | None = None
    provider: str | None = None
    model: str | None = None
    duration_ms: int = 0
    success: bool
    error: str | None = None
    actor: str = "backend"
    action: str = ""
    entity_type: str = ""
    run_id: str | None = None


class Suppression(Record):
    prefix: ClassVar[str] = "sup"
    id: str = Field(default_factory=lambda: "sup_" + str(uuid4()))
    company_id: str | None = None
    do_not_contact: bool = False
    opted_out: bool = False
    bounced: bool = False
    reason: str = ""
    domain: str = ""
    email: str = ""
    created_by: str = "Local reviewer"
    active: bool = True


class ContactEvent(Record):
    prefix: ClassVar[str] = "con"
    id: str = Field(default_factory=lambda: "con_" + str(uuid4()))
    company_id: str
    opportunity_id: str
    status: str
    channel: str


class SystemConfig(Record):
    key: str
    value: str

    @field_validator("key")
    @classmethod
    def non_secret_key(cls, value):
        if value not in {
            "ACTIVE_VERTICALS",
            "EMAIL_SEND_ENABLED",
            "MIN_HOT_SCORE",
            "MIN_STRONG_SCORE",
            "DEFAULT_RECENCY_DAYS",
            "KNOWLEDGE_VERSION",
            "SCORING_VERSION",
            "LAST_COMMIT_ID",
        }:
            raise ValueError("Only documented non-sensitive system settings are allowed")
        return value


RECORD_TYPES = {cls.__name__: cls for cls in Record.__subclasses__()}
