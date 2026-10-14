"""Read-only research candidates derived from canonical sources, never Opportunities."""

import re
from datetime import date
from uuid import NAMESPACE_URL, uuid5

from leados.engine import detect_signals
from leados.knowledge import knowledge
from leados.qualification import NOISE, SCOPES, company_name_supported, qualify
from leados.services.identity import document_heading
from leados.services.provenance import qualified_opportunity
from leados.storage.base import StorageProvider
from leados.storage.records import Company, CompanyAlias, Opportunity, SourceDocument


def live_prospects(storage: StorageProvider) -> list[dict]:
    companies = {c.id: c for c in storage.list(Company) if c.record_origin == "LIVE" and not c.archived_at}
    aliases: dict[str, list[str]] = {}
    for alias in storage.list(CompanyAlias):
        aliases.setdefault(alias.company_id, []).append(alias.name)
    qualified = {
        (o.company_id, o.vertical_id) for o in storage.list(Opportunity) if qualified_opportunity(o, "LIVE")
    }
    rows: dict[tuple[str, str], dict] = {}
    documents = sorted(storage.list(SourceDocument), key=lambda d: (d.retrieved_at, d.id), reverse=True)
    for doc in documents:
        company = companies.get(doc.company_id)
        if (
            not company
            or document_heading(company.canonical_name)
            or doc.record_origin != "LIVE"
            or doc.archived_at
            or doc.assertion_type != "FACT"
            or doc.conflict
            or not doc.company_match
            or doc.confidence < 0.6
            or not doc.source_url.startswith(("https://", "http://"))
            or re.search(NOISE, doc.snippet.casefold())
        ):
            continue
        identity = {"name": company.canonical_name, "aliases": aliases.get(company.id, [])}
        if not company_name_supported(identity, doc.snippet):
            continue
        document = {**doc.model_dump(mode="json"), "company": identity}
        qualification = qualify(document)
        role_check = qualify({**document, "provenance": {}, "crawler_error": None})
        if role_check["organization_role"] == "SOLUTION_PROVIDER":
            continue
        signal_ids = detect_signals(doc.snippet, knowledge.signals, live=True)
        if not signal_ids:
            continue
        # A concrete catalogue event routes to its primary scope, not all related verticals.
        # Rank only detected catalogue events. Long procurement documents may mention
        # ancillary privacy/vendor controls; the main scope should drive the one row.
        heading = (doc.title + " " + doc.snippet[:2000]).casefold()

        def relevance(signal_id, heading=heading, doc=doc, signal_ids=signal_ids):
            signal = knowledge.signals[signal_id]
            scope = SCOPES.get(signal.vertical_ids[0], r"(?!)")
            return (
                20 * len(re.findall(scope, heading)) + len(re.findall(scope, doc.snippet.casefold())),
                -signal_ids.index(signal_id),
            )

        signal = knowledge.signals[max(signal_ids, key=relevance)]
        vertical = knowledge.verticals[signal.vertical_ids[0]]
        key = (company.id, vertical.id)
        if key in qualified:
            continue
        timely = bool(doc.published_date and 0 <= (date.today() - doc.published_date).days <= 90)
        status = (
            "POTENTIAL_PROSPECT" if timely and not doc.provenance.get("source_error") else "NEEDS_RESEARCH"
        )
        service = next((s for s in signal.possible_services if s in vertical.services), vertical.services[0])
        row_id = "prospect_" + str(uuid5(NAMESPACE_URL, f"leados:prospect:{company.id}:{vertical.id}"))
        if key in rows:
            rows[key]["sources"].append({"id": doc.id, "url": doc.source_url, "title": doc.title})
            continue
        passages = [p.strip() for p in re.split(r"[\n]+|(?<=[.!?])\s+", doc.snippet) if p.strip()]
        event = next(
            (p for p in passages if signal.signal_id in detect_signals(p, knowledge.signals, live=True)),
            doc.snippet.strip()[:400],
        )
        rows[key] = {
            "id": row_id,
            "record_type": "POTENTIAL_PROSPECT",
            "record_origin": "LIVE",
            "company_id": company.id,
            "company": company.canonical_name,
            "industry": company.sector,
            "country": company.country,
            "domain": company.domain,
            "trigger": event[:400],
            "trigger_date": doc.published_date.isoformat() if doc.published_date else None,
            "vertical_id": vertical.id,
            "vertical": vertical.name,
            "recommended_service": service,
            "why_now": f"The catalog matches {signal.name.lower()}. Assess relevance to {service}; external purchasing intent is unconfirmed.",
            "research_status": status,
            "confidence": doc.confidence,
            "evidence_status": "SOURCE_ACCESS_RESTRICTED"
            if "restricted" in str(doc.provenance.get("source_error", "")).casefold()
            else "SOURCE_EXTRACTION_UNAVAILABLE"
            if doc.provenance.get("source_error")
            else "SOURCE_REPORTED",
            "source": doc.source_url,
            "primary_source_id": doc.id,
            "source_title": doc.title,
            "source_excerpt": doc.snippet,
            "retrieved_at": doc.retrieved_at.isoformat(),
            "sources": [{"id": doc.id, "url": doc.source_url, "title": doc.title}],
            "buyer_roles": vertical.buyer_roles,
            "contact_status": "RECOMMENDED_ROLE_ONLY",
            "qualification": qualification,
            "uncertainty": "Verify source timing, current scope and external advisory demand before outreach.",
            "next_action": "Research further; human review required before outreach.",
            "updated_at": doc.retrieved_at.isoformat(),
        }
    return sorted(rows.values(), key=lambda r: (r["company"], r["vertical_id"]))
