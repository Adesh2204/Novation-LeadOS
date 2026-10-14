from uuid import NAMESPACE_URL, uuid5

from leados.knowledge import knowledge
from leados.providers.base import ProviderError
from leados.providers.future.contacts import ContactOutContactProvider, SnovioContactProvider
from leados.safety import is_suppressed
from leados.storage.records import (
    AuditLog,
    Company,
    DecisionMakerRole,
    Opportunity,
    OpportunityEvidence,
    SourceDocument,
)


def require_live_lead(db, opportunity: Opportunity):
    company = db.get(Company, opportunity.company_id)
    if company is None or not company.domain:
        raise ProviderError("company_domain_required", retryable=False)
    sources = [
        db.get(SourceDocument, link.document_id)
        for link in db.list(OpportunityEvidence, opportunity_id=opportunity.id)
    ]
    if (
        opportunity.record_origin != "LIVE"
        or opportunity.archived_at
        or not sources
        or any(
            source
            and (
                source.record_origin != "LIVE"
                or source.archived_at
                or ".example" in source.source_url
                or "example.com" in source.source_url
            )
            for source in sources
        )
    ):
        raise ProviderError("synthetic_lead_external_actions_disabled", retryable=False)
    minimum = next(band["min"] for band in knowledge.scoring["bands"] if band["name"] == "STRONG")
    if (
        opportunity.audit_status != "VERIFIED"
        or opportunity.score < minimum
        or opportunity.qualification.get("status") != "QUALIFIED_SIGNAL"
    ):
        raise ProviderError("verified_strong_lead_required", retryable=False)
    if is_suppressed(db, company.id):
        raise ProviderError("company_suppressed", retryable=False)
    return company


async def enrich_contacts(db, opportunity: Opportunity) -> dict:
    company = require_live_lead(db, opportunity)
    existing = [
        role for role in db.list(DecisionMakerRole, opportunity_id=opportunity.id) if role.person_name
    ]
    if existing:
        return {"status": "CACHED", "contacts": [role.model_dump(mode="json") for role in existing]}
    roles = [role.role for role in db.list(DecisionMakerRole, opportunity_id=opportunity.id)][:3]
    if not roles:
        raise ProviderError("buyer_roles_required", retryable=False)
    # One search (at most three work profiles) and one verification batch. Never a campaign/send API.
    contacts = await ContactOutContactProvider().enrich(
        {"name": company.canonical_name, "domain": company.domain}, roles
    )
    verification_error = None
    try:
        statuses = await SnovioContactProvider().verify([contact["contact_email"] for contact in contacts])
    except ProviderError as error:
        statuses = {}
        verification_error = error.code
    records: list[DecisionMakerRole] = []
    for contact in contacts:
        if any(record.role == contact["role"] for record in records):
            continue
        contact["contact_status"] = statuses.get(contact["contact_email"], "FOUND_UNVERIFIED")
        contact["contact_source"] = (
            "ContactOut + Snov.io" if contact["contact_status"] == "VALIDATED" else "ContactOut"
        )
        identifier = "buy_" + str(uuid5(NAMESPACE_URL, opportunity.id + contact["contact_email"]))
        record = db.first(DecisionMakerRole, opportunity_id=opportunity.id, role=contact["role"])
        if record is None:
            record = DecisionMakerRole(
                id=identifier,
                opportunity_id=opportunity.id,
                rationale="Current company and buyer role matched by ContactOut; work email checked by Snov.io",
                **contact,
            )
        else:
            for key, value in contact.items():
                setattr(record, key, value)
            record.rationale = (
                "Current company and buyer role matched by ContactOut; work email checked by Snov.io"
            )
        db.add(record)
        records.append(record)
    db.add(
        AuditLog(
            module="contact_enrichment",
            input_ref=opportunity.id,
            provider="contactout+snovio",
            success=not verification_error,
            error=verification_error,
        )
    )
    db.flush()
    return {
        "status": "PARTIAL" if verification_error else "COMPLETED",
        "contacts": [role.model_dump(mode="json") for role in records],
        "error": verification_error,
        "email_sent": False,
    }
