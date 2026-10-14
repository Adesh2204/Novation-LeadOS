from leados.config import Settings
from leados.providers.base import ProviderError
from leados.providers.base.email import EmailProvider
from leados.storage.base import StorageProvider
from leados.storage.records import (
    Company,
    ContactEvent,
    DecisionMakerRole,
    HumanReview,
    Opportunity,
    OutreachDraft,
    Suppression,
)


def is_suppressed(db: StorageProvider, company_id: str) -> bool:
    company = db.get(Company, company_id)
    for record in db.list(Suppression):
        matches = record.company_id == company_id or bool(
            company and record.domain and record.domain.lower().removeprefix("www.") == company.domain
        )
        if (
            matches
            and record.active
            and (
                record.do_not_contact
                or record.opted_out
                or record.bounced
                or bool(record.domain)
                or bool(record.email)
            )
        ):
            return True
    return False


async def guarded_send(
    db: StorageProvider, opportunity: Opportunity, body: str, config: Settings, provider: EmailProvider
):
    if opportunity.human_status != "APPROVED":
        raise ProviderError("human_approval_required")
    reviews = sorted(db.list(HumanReview, opportunity_id=opportunity.id), key=lambda r: r.created_at)
    if not reviews or reviews[-1].decision != "APPROVED":
        raise ProviderError("approved_review_required")
    if opportunity.audit_status != "VERIFIED":
        raise ProviderError("verified_evidence_required")
    if is_suppressed(db, opportunity.company_id):
        raise ProviderError("company_suppressed")
    if db.first(ContactEvent, company_id=opportunity.company_id):
        raise ProviderError("previous_contact_requires_review")
    if not config.enable_email_send:
        raise ProviderError("email_send_disabled")
    draft = db.first(OutreachDraft, opportunity_id=opportunity.id)
    if not draft or not draft.human_approved:
        raise ProviderError("approved_draft_required")
    contacts = [
        r
        for r in db.list(DecisionMakerRole, opportunity_id=opportunity.id)
        if r.contact_status == "VALIDATED"
        and r.person_name
        and r.contact_email
        and "@" in r.contact_email
        and r.contact_source
    ]
    if not contacts:
        raise ProviderError("contact_validation_required")
    if any(
        s.active and s.email and s.email.casefold() == c.contact_email.casefold()
        for c in contacts
        for s in db.list(Suppression)
    ):
        raise ProviderError("contact_suppressed")
    # V1 has an independent hard stop. An environment flag can never turn on transport.
    raise ProviderError("email_transport_disabled_in_v1")
