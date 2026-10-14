"""Workbook schemas and reversible typed row mapping; no business decisions."""

import json
from dataclasses import dataclass
from typing import get_origin

from leados.storage.base import StorageError
from leados.storage.records import RECORD_TYPES, Record

WORKBOOK_NAME = "NOVATION_LEADOS_MASTER"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
ADDITIVE_FIELDS = {
    "record_origin",
    "provenance",
    "archived_at",
    "content_history",
    "qualification",
    "score_inputs",
    "evaluation_history",
}

# Required human-readable columns are first. Extra columns preserve lossless domain data.
HEADERS = {
    "COMPANIES": "company_id canonical_name domain country industry employee_range funding_stage description primary_location website linkedin_url status created_at updated_at last_seen_at",
    "COMPANY_ALIASES": "alias_id company_id alias_name alias_domain source confidence created_at",
    "SOURCES": "source_id source_url source_name source_type published_date retrieved_at content_hash company_id title snippet raw_text_reference confidence created_at",
    "SIGNALS": "signal_id signal_name description vertical_ids base_strength recency_policy source_requirement status knowledge_version",
    "COMPANY_SIGNALS": "company_signal_id company_id signal_id source_id detected_at event_date confidence status first_seen_at last_seen_at detection_version",
    "OPPORTUNITIES": "opportunity_id company_id company_name primary_vertical secondary_verticals opportunity_type trigger trigger_date recommended_service why_now decision_maker_roles need_score icp_fit_score trigger_strength_score recency_score mandate_value_score decision_maker_score expertise_match_score evidence_quality_score total_score score_band confidence evidence_status human_status recommended_action outreach_angle knowledge_version signal_version score_version created_at updated_at opportunity_fingerprint",
    "OPPORTUNITY_EVIDENCE": "evidence_id opportunity_id company_id source_id fact_type fact_text inference_text source_url source_name published_date retrieved_at evidence_confidence verification_status created_at",
    "SCORE_COMPONENTS": "score_component_id opportunity_id component_name points maximum rationale created_at",
    "BUYER_ROLES": "buyer_role_id opportunity_id company_id role_title role_priority reason person_name contact_status contact_source confidence created_at",
    "OUTREACH_DRAFTS": "outreach_id opportunity_id company_id subject message outreach_angle recommended_service generated_at generation_version human_approved approved_by approved_at send_status sent_at",
    "HUMAN_REVIEWS": "review_id opportunity_id reviewer decision notes reviewed_at",
    "FEEDBACK": "feedback_id opportunity_id company_id status reason notes recorded_by recorded_at score_snapshot score_version knowledge_version signal_version buyer_role",
    "SUPPRESSION_LIST": "suppression_id company_id domain email reason created_at created_by active do_not_contact opted_out bounced",
    "PROVIDER_RUNS": "snapshot_id run_id provider operation started_at completed_at status items_processed items_created duplicates_skipped errors duration_ms revision",
    "AUDIT_LOG": "audit_id timestamp actor module action entity_type entity_id input_reference output_reference result error_message run_id provider model duration_ms",
    "SYSTEM_CONFIG": "config_id key value created_at",
    "SOURCE_PUBLISHERS": "publisher_id name source_type origin reliability created_at",
    "HUMAN_REVIEW_TASKS": "task_id opportunity_id status reason created_at",
    "CONTACT_EVENTS": "contact_event_id company_id opportunity_id status channel created_at",
}
ENTITY_TABS = {
    "Company": "COMPANIES",
    "CompanyAlias": "COMPANY_ALIASES",
    "SourceDocument": "SOURCES",
    "Signal": "SIGNALS",
    "CompanySignal": "COMPANY_SIGNALS",
    "Opportunity": "OPPORTUNITIES",
    "OpportunityEvidence": "OPPORTUNITY_EVIDENCE",
    "ScoreComponent": "SCORE_COMPONENTS",
    "DecisionMakerRole": "BUYER_ROLES",
    "OutreachDraft": "OUTREACH_DRAFTS",
    "HumanReview": "HUMAN_REVIEWS",
    "FeedbackEvent": "FEEDBACK",
    "Suppression": "SUPPRESSION_LIST",
    "ProviderRun": "PROVIDER_RUNS",
    "AuditLog": "AUDIT_LOG",
    "SystemConfig": "SYSTEM_CONFIG",
    "Source": "SOURCE_PUBLISHERS",
    "HumanReviewTask": "HUMAN_REVIEW_TASKS",
    "ContactEvent": "CONTACT_EVENTS",
}
ALIASES = {
    "Company": {"id": "company_id", "sector": "industry", "merge_confidence": "entity_resolution_confidence"},
    "CompanyAlias": {"id": "alias_id", "name": "alias_name"},
    "SourceDocument": {"id": "source_id", "source_id": "publisher_id"},
    "Signal": {"id": "signal_id", "code": "signal_key", "version": "knowledge_version"},
    "CompanySignal": {"id": "company_signal_id", "created_at": "first_seen_at"},
    "Opportunity": {
        "id": "opportunity_id",
        "vertical_id": "primary_vertical",
        "score": "total_score",
        "audit_status": "evidence_status",
    },
    "OpportunityEvidence": {"id": "evidence_id", "document_id": "source_id"},
    "ScoreComponent": {"id": "score_component_id", "name": "component_name"},
    "DecisionMakerRole": {"id": "buyer_role_id", "role": "role_title", "rationale": "reason"},
    "OutreachDraft": {"id": "outreach_id", "body": "message", "created_at": "generated_at"},
    "HumanReview": {"id": "review_id", "created_at": "reviewed_at"},
    "FeedbackEvent": {"id": "feedback_id", "created_at": "recorded_at"},
    "Suppression": {"id": "suppression_id"},
    "ProviderRun": {"id": "run_id", "stage": "operation", "created_at": "started_at"},
    "AuditLog": {
        "id": "audit_id",
        "created_at": "timestamp",
        "input_ref": "input_reference",
        "output_ref": "output_reference",
        "error": "error_message",
    },
    "SystemConfig": {"id": "config_id"},
    "Source": {"id": "publisher_id"},
    "HumanReviewTask": {"id": "task_id"},
    "ContactEvent": {"id": "contact_event_id"},
}
ENUMS = {
    "score_band": ["HOT", "STRONG", "MONITOR", "IGNORE"],
    "human_status": ["PENDING_REVIEW", "APPROVED", "REJECTED", "NEEDS_RESEARCH", "MONITOR"],
    "evidence_status": ["VERIFIED", "NEEDS_RESEARCH", "INSUFFICIENT_EVIDENCE", "REJECTED"],
    "verification_status": ["VERIFIED", "NEEDS_RESEARCH", "INSUFFICIENT_EVIDENCE", "REJECTED"],
    "fact_type": ["FACT", "ALLEGATION", "INFERENCE", "COMMERCIAL_THESIS"],
    "decision": ["APPROVED", "REJECTED", "NEEDS_RESEARCH", "MONITOR"],
}
FEEDBACK_STATUSES = [
    "NOT_RELEVANT",
    "CONTACTED",
    "NO_RESPONSE",
    "RESPONDED",
    "MEETING",
    "PROPOSAL",
    "ENGAGED",
    "WON",
    "LOST",
]
FEEDBACK_REASONS = [
    "WRONG_COMPANY",
    "WRONG_TIMING",
    "WRONG_SERVICE",
    "NO_BUDGET",
    "NO_RELATIONSHIP",
    "CONFLICT",
    "EXISTING_COUNSEL",
    "NO_NEED",
    "OTHER",
]
SCORE_COLUMNS = dict(
    zip(
        "identifiable_need icp_fit trigger_strength trigger_recency mandate_value buyer_reachability expertise_match evidence_quality".split(),
        "need_score icp_fit_score trigger_strength_score recency_score mandate_value_score decision_maker_score expertise_match_score evidence_quality_score".split(),
        strict=True,
    )
)


def column_name(index: int) -> str:
    result = ""
    while index:
        index, digit = divmod(index - 1, 26)
        result = chr(65 + digit) + result
    return result


def cell(value):
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


@dataclass
class SheetSchema:
    entity: str
    tab: str
    headers: list[str]
    aliases: dict[str, str]

    @property
    def model(self):
        return RECORD_TYPES[self.entity]

    def validate_headers(self, headers: list[str]):
        if len(headers) != len(set(headers)):
            raise StorageError("duplicate_header", self.tab)
        for required in self.headers:
            if required not in headers and required not in ADDITIVE_FIELDS:
                raise StorageError("missing_column", f"{self.tab} sheet missing column {required}.")

    def decode(self, headers: list[str], values: list):
        self.validate_headers(headers)
        row = dict(zip(headers, [*values, *([""] * max(0, len(headers) - len(values)))], strict=False))
        for key, allowed in ENUMS.items():
            if key in row and row[key] not in allowed:
                raise StorageError("invalid_enum", f"{self.tab}.{key}")
        if self.entity == "FeedbackEvent":
            if row["status"] not in FEEDBACK_STATUSES or (
                row["reason"] and row["reason"] not in FEEDBACK_REASONS
            ):
                raise StorageError("invalid_enum", "FEEDBACK.status/reason")
            row["status"] = row["status"].replace("_", " ").title()
            row["reason"] = row["reason"].replace("_", " ").title() if row["reason"] else None
        data = {}
        for field, info in self.model.model_fields.items():
            column = self.aliases.get(field, field)
            value = row.get(column, "")
            if self.entity == "ProviderRun" and field == "state":
                value = "".join(str(row.get("state" if i == 0 else f"state_{i + 1}", "")) for i in range(16))
            if value == "" or value is None:
                if info.annotation is bool:
                    raise StorageError("missing_value", f"{self.tab}.{column}")
                if field in {"notes", "snippet", "description"}:
                    data[field] = ""
                    continue
                if field in {
                    "id",
                    "created_at",
                    "retrieved_at",
                    "updated_at",
                    "last_seen_at",
                    "status",
                    "human_status",
                    "score_band",
                    "audit_status",
                }:
                    raise StorageError("missing_value", f"{self.tab}.{column}")
                if info.is_required():
                    raise StorageError("missing_value", f"{self.tab}.{column}")
                continue
            annotation = info.annotation
            if get_origin(annotation) in {list, dict} or annotation in {list, dict}:
                value = json.loads(value) if isinstance(value, str) else value
            elif annotation is bool and isinstance(value, str):
                if value.upper() not in {"TRUE", "FALSE"}:
                    raise StorageError("invalid_boolean", f"{self.tab}.{column}")
                value = value.upper() == "TRUE"
            elif annotation is int and isinstance(value, str):
                value = int(value)
            elif annotation is int and isinstance(value, float) and value.is_integer():
                value = int(value)
            data[field] = value
        if self.entity == "Opportunity" and not data.get("opportunity_fingerprint"):
            raise StorageError("missing_value", "OPPORTUNITIES.opportunity_fingerprint")
        return self.model.model_validate(data)

    def encode(self, record: Record, storage, *, snapshot_id: str = "") -> dict:
        data = record.model_dump(mode="json")
        row = {self.aliases.get(k, k): cell(v) for k, v in data.items()}
        from leados.storage.records import (
            AuditLog,
            Company,
            CompanySignal,
            DecisionMakerRole,
            FeedbackEvent,
            Opportunity,
            OpportunityEvidence,
            OutreachDraft,
            ProviderRun,
            ScoreComponent,
            Service,
            Signal,
            Source,
            SourceDocument,
        )

        company = storage.get(Company, getattr(record, "company_id", ""))
        opportunity = storage.get(Opportunity, getattr(record, "opportunity_id", ""))
        if not company and opportunity:
            company = storage.get(Company, opportunity.company_id)
        if company:
            row["company_name"], row["company_id"] = company.canonical_name, company.id
        if isinstance(record, Company):
            row["primary_location"] = ", ".join(record.locations)
        elif isinstance(record, SourceDocument):
            publisher = storage.get(Source, record.source_id)
            row["source_name"] = publisher.name if publisher else ""
            row["source_type"] = publisher.source_type if publisher else "OTHER"
        elif isinstance(record, Signal):
            d = record.definition
            row.update(
                signal_name=d["name"],
                description=d["description"],
                vertical_ids="|".join(d["vertical_ids"]),
                base_strength=d["base_strength"],
                recency_policy=d["recency_decay"],
                source_requirement=d["source_reliability_requirement"],
                status="ACTIVE",
            )
        elif isinstance(record, CompanySignal):
            row.update(
                source_id=record.evidence_ids[0] if record.evidence_ids else "",
                detected_at=data["created_at"],
            )
        elif isinstance(record, Opportunity):
            service = storage.get(Service, record.service_id)
            signal = storage.get(CompanySignal, record.company_signal_id)
            from leados.knowledge import knowledge

            secondary = knowledge.signals[signal.signal_key].vertical_ids if signal else []
            row.update(
                secondary_verticals="|".join(v for v in secondary if v != record.vertical_id),
                opportunity_type=record.trigger,
                recommended_service=service.name if service else "",
                decision_maker_roles="|".join(
                    r.role for r in storage.list(DecisionMakerRole, opportunity_id=record.id)
                ),
                recommended_action="Human review"
                if record.audit_status == "VERIFIED"
                else "Research required",
            )
            for part in storage.list(ScoreComponent, opportunity_id=record.id):
                row[SCORE_COLUMNS[part.name]] = part.points
        elif isinstance(record, OpportunityEvidence):
            doc = storage.get(SourceDocument, record.document_id)
            publisher = storage.get(Source, doc.source_id) if doc else None
            if doc:
                row.update(
                    fact_type=doc.assertion_type,
                    fact_text=doc.snippet if doc.assertion_type in {"FACT", "ALLEGATION"} else "",
                    inference_text=doc.snippet
                    if doc.assertion_type in {"INFERENCE", "COMMERCIAL_THESIS"}
                    else "",
                    source_url=doc.source_url,
                    source_name=publisher.name if publisher else "",
                    published_date=str(doc.published_date) if doc.published_date else "",
                    retrieved_at=doc.retrieved_at.isoformat(),
                    evidence_confidence=doc.confidence,
                    verification_status=opportunity.audit_status if opportunity else "INSUFFICIENT_EVIDENCE",
                )
        elif isinstance(record, DecisionMakerRole):
            row["role_priority"] = 1
        elif isinstance(record, OutreachDraft):
            service = storage.get(Service, opportunity.service_id) if opportunity else None
            row.update(
                subject=record.subjects[0] if record.subjects else "",
                outreach_angle=opportunity.outreach_angle if opportunity else "",
                recommended_service=service.name if service else "",
            )
        elif isinstance(record, FeedbackEvent):
            row["status"] = record.status.replace(" ", "_").upper()
            row["reason"] = record.reason.replace(" ", "_").upper() if record.reason else ""
        elif isinstance(record, ProviderRun):
            serialized = cell(record.state)
            max_state_len = 16 * 45000
            if len(serialized) > max_state_len:
                serialized = serialized[: max_state_len - 30] + "... [TRUNCATED]"
            for i in range(16):
                row["state" if i == 0 else f"state_{i + 1}"] = serialized[i * 45000 : (i + 1) * 45000]
            row.update(
                snapshot_id=snapshot_id,
                items_processed=record.metrics.get("processed", 0),
                items_created=record.metrics.get("opportunities_created", 0),
                duplicates_skipped=record.metrics.get("duplicates_avoided", 0),
                errors=record.metrics.get("errors", 0),
            )
        elif isinstance(record, AuditLog):
            row.update(entity_id=record.output_ref or "", result="SUCCESS" if record.success else "FAILURE")
        return row


SCHEMAS: dict[str, SheetSchema] = {}
for entity, tab in ENTITY_TABS.items():
    aliases = ALIASES.get(entity, {})
    headers = HEADERS[tab].split()
    for field in RECORD_TYPES[entity].model_fields:
        column = aliases.get(field, field)
        if column not in headers:
            headers.append(column)
    if entity == "ProviderRun":
        headers.extend(f"state_{i}" for i in range(2, 17))
    SCHEMAS[tab] = SheetSchema(entity, tab, headers, aliases)

REQUIRED_TABS = list(HEADERS)[:16]
