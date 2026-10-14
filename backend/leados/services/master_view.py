"""One read-only presentation row per opportunity; domain records stay authoritative."""

import hashlib
import json
from collections import defaultdict
from datetime import date

from leados.engine import audit_evidence
from leados.knowledge import knowledge
from leados.pipeline import evidence_for
from leados.services.prospects import live_prospects
from leados.services.provenance import DataMode, qualified_opportunity
from leados.storage.base import StorageError, StorageProvider
from leados.storage.records import (
    Company,
    CompanySignal,
    DecisionMakerRole,
    FeedbackEvent,
    HumanReview,
    Opportunity,
    OpportunityEvidence,
    OutreachDraft,
    ProviderRun,
    Service,
    SourceDocument,
    Vertical,
)

PROJECTION_TYPES = (
    Company,
    CompanySignal,
    SourceDocument,
    Opportunity,
    OpportunityEvidence,
    DecisionMakerRole,
    HumanReview,
    OutreachDraft,
    FeedbackEvent,
)
type OpportunityChild = OpportunityEvidence | DecisionMakerRole | HumanReview | OutreachDraft | FeedbackEvent


class MasterViewService:
    def __init__(self, storage: StorageProvider):
        self.storage = storage

    def fingerprint(self) -> str:
        data = {
            model.__name__: [
                r.model_dump(mode="json") for r in sorted(self.storage.list(model), key=lambda r: r.id)
            ]
            for model in PROJECTION_TYPES
        }
        data["discovery_results"] = [
            {"id": run.id, "results": run.state["discovery_results"]}
            for run in sorted(self.storage.list(ProviderRun), key=lambda run: run.id)
            if "discovery_results" in run.state
        ]
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def build_rows(self, data_mode: DataMode = "LIVE") -> list[dict]:
        if self.storage.quarantined_ids:
            raise StorageError(
                "master_view_source_invalid",
                "Correct quarantined technical records before syncing the overview",
            )
        companies = {r.id: r for r in self.storage.list(Company)}
        documents = {r.id: r for r in self.storage.list(SourceDocument)}
        services = {r.id: r for r in self.storage.list(Service)}
        verticals = {r.id: r for r in self.storage.list(Vertical)}
        signals = {r.id: r for r in self.storage.list(CompanySignal)}
        grouped: dict[type[OpportunityChild], defaultdict[str, list]] = {}
        group_types: tuple[type[OpportunityChild], ...] = (
            OpportunityEvidence,
            DecisionMakerRole,
            HumanReview,
            OutreachDraft,
            FeedbackEvent,
        )
        for model in group_types:
            index: defaultdict[str, list] = defaultdict(list)
            for record in self.storage.list(model):
                index[record.opportunity_id].append(record)
            grouped[model] = index
        result = []
        for opportunity in self.storage.list(Opportunity):
            if not qualified_opportunity(opportunity, data_mode):
                continue
            company = companies.get(opportunity.company_id)
            service = services.get(opportunity.service_id)
            vertical = verticals.get(opportunity.vertical_id)
            signal = signals.get(opportunity.company_signal_id)
            if not company or not service or not vertical or not signal:
                raise StorageError("master_view_missing_reference", "Opportunity")
            selected = None
            if opportunity.audit_status == "VERIFIED":
                candidates = []
                for link in grouped[OpportunityEvidence][opportunity.id]:
                    document = documents.get(link.document_id)
                    if not document or document.company_id != company.id:
                        continue
                    # Reuse the official auditor to qualify an individual source, never a Sheet formula.
                    status, _, _ = audit_evidence(
                        evidence_for(self.storage, [document.id]),
                        knowledge.signals[signal.signal_key],
                        date.today(),
                        [],
                        knowledge,
                        live=True,
                    )
                    if status == "VERIFIED":
                        candidates.append(document)
                if candidates:
                    selected = sorted(
                        candidates,
                        key=lambda d: (
                            -d.confidence,
                            -(d.published_date or date.min).toordinal(),
                            -d.retrieved_at.timestamp(),
                            d.id,
                        ),
                    )[0]
            elif data_mode == "LIVE" and opportunity.qualification.get("service_demand"):
                candidates = [
                    documents[link.document_id]
                    for link in grouped[OpportunityEvidence][opportunity.id]
                    if link.document_id in documents and documents[link.document_id].company_id == company.id
                ]
                if candidates:
                    selected = sorted(
                        candidates,
                        key=lambda d: (
                            -d.confidence,
                            -(d.published_date or date.min).toordinal(),
                            -d.retrieved_at.timestamp(),
                            d.id,
                        ),
                    )[0]
            roles = grouped[DecisionMakerRole][opportunity.id]
            priority = vertical.definition.get("buyer_roles", [])
            buyer = (
                min(
                    roles,
                    key=lambda r: (
                        priority.index(r.role) if r.role in priority else len(priority),
                        -r.confidence,
                        r.role,
                        r.id,
                    ),
                ).role
                if roles
                else ""
            )
            reviews = grouped[HumanReview][opportunity.id]
            latest_review = max(reviews, key=lambda r: (r.created_at, r.id)) if reviews else None
            review_status = (
                latest_review.decision
                if latest_review
                else (
                    "PENDING_REVIEW"
                    if (opportunity.audit_status == "VERIFIED" or opportunity.qualification.get("service_demand"))
                    else "NEEDS_RESEARCH"
                )
            )
            drafts = grouped[OutreachDraft][opportunity.id]
            draft = max(drafts, key=lambda r: (r.created_at, r.id)) if drafts else None
            angle = str(draft.subjects[0]) if draft and draft.subjects else opportunity.outreach_angle
            evidence_status = (
                "VERIFIED"
                if opportunity.audit_status == "VERIFIED" and selected
                else ("REJECTED" if opportunity.audit_status == "REJECTED" else "NEEDS RESEARCH")
            )
            timestamps = [opportunity.updated_at, company.updated_at]
            timestamps.extend(r.created_at for r in reviews + drafts + grouped[FeedbackEvent][opportunity.id])
            result.append(
                {
                    "company": company.canonical_name,
                    "industry": company.sector,
                    "country": company.country,
                    "trigger": opportunity.trigger,
                    "trigger_date": opportunity.trigger_date.isoformat() if opportunity.trigger_date else "",
                    "vertical": vertical.definition["name"],
                    "recommended_service": service.name,
                    "why_now": opportunity.why_now,
                    "score": opportunity.score,
                    "score_status": opportunity.score_band,
                    "confidence": opportunity.confidence,
                    "evidence_status": evidence_status,
                    "source": selected.source_url if selected else "",
                    "buyer": buyer,
                    "review_status": review_status.replace("_", " "),
                    "outreach_angle": angle,
                    "opportunity_id": opportunity.id,
                    "row_id": opportunity.id,
                    "record_type": "QUALIFIED_OPPORTUNITY",
                    "research_status": "VERIFIED_QUALIFIED" if data_mode == "LIVE" else "MOCK_FIXTURE",
                    "contact_status": "RECOMMENDED_ROLE_ONLY",
                    "company_id": company.id,
                    "primary_source_id": selected.id if selected else "",
                    "updated_at": max(timestamps).isoformat().replace("+00:00", "Z"),
                }
            )
        if data_mode == "LIVE":
            for prospect in live_prospects(self.storage):
                result.append(
                    {
                        **prospect,
                        "row_id": prospect["id"],
                        "trigger_date": prospect["trigger_date"] or "",
                        "opportunity_id": "",
                        "score": "",
                        "score_status": "UNSCORED",
                        "buyer": ", ".join(prospect["buyer_roles"]),
                        "review_status": "NEEDS RESEARCH",
                        "outreach_angle": prospect["next_action"],
                    }
                )
        result.sort(
            key=lambda r: (
                -(r["score"] or 0),
                -date.fromisoformat(r["trigger_date"]).toordinal() if r["trigger_date"] else 0,
                r["row_id"],
            )
        )
        return result
