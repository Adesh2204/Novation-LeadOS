"""Evidence-based origin classification and reversible logical archival, never deletion."""

from collections import Counter
from datetime import UTC, datetime
from typing import Literal, cast

from leados.config import ROOT
from leados.engine import canonical_url, digest
from leados.storage.base import StorageProvider
from leados.storage.records import (
    AuditLog,
    Company,
    CompanySignal,
    Opportunity,
    OpportunityEvidence,
    ProviderRun,
    Source,
    SourceDocument,
)

DataMode = Literal["LIVE", "MOCK", "LEGACY_UNKNOWN"]
CORE_TYPES = (Company, Source, SourceDocument, CompanySignal, Opportunity)


def visible(record, data_mode: DataMode = "LIVE") -> bool:
    # Archived fixtures remain inspectable only in the explicitly selected development view.
    return record.record_origin == data_mode and (not record.archived_at or data_mode == "MOCK")


def qualified_opportunity(record: Opportunity, data_mode: DataMode = "LIVE") -> bool:
    return visible(record, data_mode) and (
        data_mode == "MOCK"
        or (record.qualification.get("status") == "QUALIFIED_SIGNAL" and record.audit_status == "VERIFIED")
        or record.qualification.get("service_demand", False)
    )


def classify(storage: StorageProvider) -> dict:
    import json

    fixture = json.loads((ROOT / "fixtures/market.json").read_text())
    fixture_keys = set()
    for document in fixture["documents"]:
        try:
            fixture_keys.add((canonical_url(document["source_url"]), digest(document["snippet"].strip())))
        except ValueError:
            continue  # Invalid fixture URLs were rejected by normalization and never stored.
    runs = storage.list(ProviderRun)
    live_documents: dict[str, list[str]] = {}
    for run in runs:
        if run.state.get("live_documents") is True:
            for did in run.state.get("resolved", []):
                live_documents.setdefault(did, []).append(run.id)
    plan: dict[str, dict] = {}

    def add(record, origin, reason, refs):
        plan[record.id] = {
            "entity": type(record).__name__,
            "id": record.id,
            "name": getattr(record, "canonical_name", getattr(record, "source_url", "")),
            "origin": origin,
            "reason": reason,
            "references": refs,
            "archive": origin == "MOCK",
        }

    for document in storage.list(SourceDocument):
        if (canonical_url(document.source_url), document.content_hash) in fixture_keys:
            add(document, "MOCK", "Exact synthetic fixture URL and content hash", [])
        elif document.record_origin in {"LIVE", "MOCK"} and document.provenance:
            add(document, document.record_origin, "Explicit provider provenance", [])
        elif document.id in live_documents:
            add(
                document,
                "LIVE",
                "Resolved by recorded live-document pipeline runs",
                live_documents[document.id],
            )
        else:
            add(document, "LEGACY_UNKNOWN", "No sufficient recorded origin evidence", [])

    def inherited(records):
        origins = {plan[r.id]["origin"] for r in records}
        return next(iter(origins)) if len(origins) == 1 else "LEGACY_UNKNOWN"

    for company in storage.list(Company):
        docs = storage.list(SourceDocument, company_id=company.id)
        add(company, inherited(docs), "Origin of all associated source records", [d.id for d in docs])
    for source in storage.list(Source):
        docs = storage.list(SourceDocument, source_id=source.id)
        add(source, inherited(docs), "Origin of all associated source records", [d.id for d in docs])
    for signal in storage.list(CompanySignal):
        optional_docs = [storage.get(SourceDocument, did) for did in signal.evidence_ids]
        selected = [d for d in optional_docs if d]
        add(signal, inherited(selected), "Origin of linked signal evidence", signal.evidence_ids)
    for opportunity in storage.list(Opportunity):
        links = storage.list(OpportunityEvidence, opportunity_id=opportunity.id)
        optional_docs = [storage.get(SourceDocument, link.document_id) for link in links]
        add(
            opportunity,
            inherited([d for d in optional_docs if d]),
            "Origin of linked opportunity evidence",
            [link.document_id for link in links],
        )
    counts = {
        model.__name__: dict(Counter(p["origin"] for p in plan.values() if p["entity"] == model.__name__))
        for model in CORE_TYPES
    }
    storage._validate_scores()
    # Validate every reference before an archive can be applied.
    for model in CORE_TYPES:
        for record in storage.list(model):
            storage._validate_record(record)
    return {"counts": counts, "records": list(plan.values()), "dependencies_valid": True, "deletion_count": 0}


def apply_classification(storage: StorageProvider, report: dict):
    at = datetime.now(UTC)
    models = {model.__name__: model for model in CORE_TYPES}
    for row in report["records"]:
        record = cast(
            Company | Source | SourceDocument | CompanySignal | Opportunity | None,
            storage.get(models[row["entity"]], row["id"]),
        )
        assert record is not None
        record.record_origin = row["origin"]
        record.provenance = {
            "method": "production_origin_audit_v1",
            "reason": row["reason"],
            "references": row["references"],
        }
        if row["archive"] and record.archived_at is None:
            record.archived_at = at
        storage.add(record)
    storage.add(AuditLog(module="production_origin_audit", action="reversible_archive", success=True))
