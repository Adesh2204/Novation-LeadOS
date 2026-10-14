from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from leados.db import Base


def now():
    return datetime.now(UTC)


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Company(Record, Base):
    __tablename__ = "companies"
    identity_key: Mapped[str] = mapped_column(String(300), unique=True)
    canonical_name: Mapped[str] = mapped_column(String(250), index=True)
    domain: Mapped[str | None] = mapped_column(String(250), index=True)
    country: Mapped[str] = mapped_column(String(80), index=True)
    sector: Mapped[str] = mapped_column(String(100), index=True)
    employee_range: Mapped[str] = mapped_column(String(50))
    funding_stage: Mapped[str] = mapped_column(String(50))
    locations: Mapped[list] = mapped_column(JSON)
    description: Mapped[str] = mapped_column(Text)
    merge_confidence: Mapped[float] = mapped_column(Float, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class CompanyAlias(Record, Base):
    __tablename__ = "company_aliases"
    __table_args__ = (UniqueConstraint("company_id", "normalized_name", "country"),)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(250))
    normalized_name: Mapped[str] = mapped_column(String(250), index=True)
    country: Mapped[str] = mapped_column(String(80))
    confidence: Mapped[float] = mapped_column(Float)


class Source(Record, Base):
    __tablename__ = "sources"
    name: Mapped[str] = mapped_column(String(250))
    source_type: Mapped[str] = mapped_column(String(80))
    origin: Mapped[str] = mapped_column(String(250), unique=True)
    reliability: Mapped[float] = mapped_column(Float)


class SourceDocument(Record, Base):
    __tablename__ = "source_documents"
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    published_date: Mapped[date | None] = mapped_column(Date)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    snippet: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    assertion_type: Mapped[str] = mapped_column(String(30))
    company_match: Mapped[bool] = mapped_column(Boolean)
    conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    author: Mapped[str | None] = mapped_column(String(250))
    jurisdiction: Mapped[str | None] = mapped_column(String(100))
    language: Mapped[str] = mapped_column(String(30), default="en")


class Vertical(Base):
    __tablename__ = "verticals"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    version: Mapped[str] = mapped_column(String(30))
    definition: Mapped[dict] = mapped_column(JSON)


class Service(Base):
    __tablename__ = "services"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    vertical_id: Mapped[str] = mapped_column(ForeignKey("verticals.id"), index=True)
    name: Mapped[str] = mapped_column(String(250))


class Signal(Base):
    __tablename__ = "signals"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    version: Mapped[str] = mapped_column(String(30))
    definition: Mapped[dict] = mapped_column(JSON)


class CompanySignal(Record, Base):
    __tablename__ = "company_signals"
    __table_args__ = (UniqueConstraint("company_id", "signal_id", "event_key"),)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    signal_id: Mapped[str] = mapped_column(ForeignKey("signals.id"), index=True)
    event_date: Mapped[date | None] = mapped_column(Date)
    event_key: Mapped[str] = mapped_column(String(100))
    confidence: Mapped[float] = mapped_column(Float)
    evidence_ids: Mapped[list] = mapped_column(JSON)


class Opportunity(Record, Base):
    __tablename__ = "opportunities"
    __table_args__ = (UniqueConstraint("company_signal_id", "vertical_id"),)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    company_signal_id: Mapped[str] = mapped_column(ForeignKey("company_signals.id"), index=True)
    vertical_id: Mapped[str] = mapped_column(ForeignKey("verticals.id"), index=True)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"))
    trigger: Mapped[str] = mapped_column(Text)
    trigger_date: Mapped[date | None] = mapped_column(Date, index=True)
    facts: Mapped[list] = mapped_column(JSON)
    allegations: Mapped[list] = mapped_column(JSON)
    inferences: Mapped[list] = mapped_column(JSON)
    commercial_thesis: Mapped[str] = mapped_column(Text)
    why_now: Mapped[str] = mapped_column(Text)
    outreach_angle: Mapped[str] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer, index=True)
    score_band: Mapped[str] = mapped_column(String(20), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    audit_status: Mapped[str] = mapped_column(String(40), index=True)
    audit_reasons: Mapped[list] = mapped_column(JSON)
    human_status: Mapped[str] = mapped_column(String(30), default="PENDING_REVIEW", index=True)
    score_version: Mapped[str] = mapped_column(String(30))
    knowledge_version: Mapped[str] = mapped_column(String(30))
    signal_version: Mapped[str] = mapped_column(String(30))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class OpportunityEvidence(Record, Base):
    __tablename__ = "opportunity_evidence"
    __table_args__ = (UniqueConstraint("opportunity_id", "document_id"),)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"), index=True)


class ScoreComponent(Record, Base):
    __tablename__ = "score_components"
    __table_args__ = (UniqueConstraint("opportunity_id", "name"),)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    points: Mapped[int] = mapped_column(Integer)
    maximum: Mapped[int] = mapped_column(Integer)
    rationale: Mapped[str] = mapped_column(Text)


class DecisionMakerRole(Record, Base):
    __tablename__ = "decision_maker_roles"
    __table_args__ = (UniqueConstraint("opportunity_id", "role"),)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), index=True)
    role: Mapped[str] = mapped_column(String(150))
    rationale: Mapped[str] = mapped_column(Text)


class OutreachDraft(Record, Base):
    __tablename__ = "outreach_drafts"
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), unique=True)
    subjects: Mapped[list] = mapped_column(JSON)
    body: Mapped[str] = mapped_column(Text)
    verified_fact_ids: Mapped[list] = mapped_column(JSON)


class HumanReview(Record, Base):
    __tablename__ = "human_reviews"
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), index=True)
    reviewer: Mapped[str] = mapped_column(String(150))
    decision: Mapped[str] = mapped_column(String(30))
    notes: Mapped[str] = mapped_column(Text)


class HumanReviewTask(Record, Base):
    __tablename__ = "human_review_tasks"
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING_REVIEW", index=True)
    reason: Mapped[str] = mapped_column(Text)


class FeedbackEvent(Record, Base):
    __tablename__ = "feedback_events"
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    reason: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str] = mapped_column(Text)
    buyer_role: Mapped[str | None] = mapped_column(String(150))
    score_snapshot: Mapped[int] = mapped_column(Integer)
    score_version: Mapped[str] = mapped_column(String(30))
    knowledge_version: Mapped[str] = mapped_column(String(30))
    signal_version: Mapped[str] = mapped_column(String(30))


class ProviderRun(Record, Base):
    __tablename__ = "provider_runs"
    provider: Mapped[str] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), index=True)
    stage: Mapped[str] = mapped_column(String(60))
    state: Mapped[dict] = mapped_column(JSON)
    metrics: Mapped[dict] = mapped_column(JSON)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class AuditLog(Record, Base):
    __tablename__ = "audit_log"
    module: Mapped[str] = mapped_column(String(100), index=True)
    input_ref: Mapped[str | None] = mapped_column(String(250))
    output_ref: Mapped[str | None] = mapped_column(String(250))
    provider: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(Text)


class Suppression(Record, Base):
    __tablename__ = "suppressions"
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), unique=True)
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False)
    bounced: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(Text, default="")


class ContactEvent(Record, Base):
    __tablename__ = "contact_events"
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), index=True)
    status: Mapped[str] = mapped_column(String(40))
    channel: Mapped[str] = mapped_column(String(40))
