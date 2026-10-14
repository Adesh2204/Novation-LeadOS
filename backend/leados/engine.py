"""Pure domain rules: canonicalization, event matching, scoring and evidence audit."""

import hashlib
import re
import unicodedata
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from leados.knowledge import Knowledge
from leados.schemas import AuditStatus, CompanyInput, Evidence, SignalDefinition
from leados.storage.base import StorageProvider
from leados.storage.records import Company, CompanyAlias
from leados.storage.repositories import CompanyRepository


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def score_band(score: int, rules: dict) -> str:
    return next(row["name"] for row in rules["bands"] if score >= row["min"])


def normalized_name(name: str) -> str:
    original = unicodedata.normalize("NFKC", name).casefold()
    name = re.sub(r"\b(pvt|private|limited|ltd|inc|llc|plc)\b", "", original)
    return re.sub(r"[\W_]+", " ", name).strip() or original.strip()


def normalized_domain(domain: str | None) -> str | None:
    if not domain:
        return None
    host = urlsplit(domain if "://" in domain else "https://" + domain).hostname
    if not host or "." not in host or re.search(r"\s", host):
        raise ValueError("invalid_company_domain")
    return host.lower().removeprefix("www.")


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("invalid_source_url")
    query = [
        (key, val)
        for key, val in parse_qsl(parts.query)
        if not key.startswith("utm_") and key not in {"fbclid", "gclid"}
    ]
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/") or "/",
            urlencode(sorted(query)),
            "",
        )
    )


def resolve_company(db: StorageProvider, data: CompanyInput) -> tuple[Company, bool]:
    domain = normalized_domain(data.domain)
    country = data.country.strip()
    key = (
        f"domain:{domain}:{country.casefold()}"
        if domain
        else f"name:{normalized_name(data.name)}:{country.casefold()}"
    )
    company = CompanyRepository(db).find(identity_key=key)
    # An alias is supporting evidence, never grounds to merge two different domains.
    if not company and not domain:
        for alias in db.list(CompanyAlias, normalized_name=normalized_name(data.name), country=country):
            candidate = db.get(Company, alias.company_id)
            if candidate and candidate.domain is None:
                company = candidate
                break
    created = company is None
    if company is None:
        company = Company(
            identity_key=key,
            canonical_name=data.name,
            domain=domain,
            country=country,
            sector=data.sector,
            employee_range=data.employee_range,
            funding_stage=data.funding_stage,
            locations=data.locations,
            description=data.description,
            merge_confidence=1 if domain else 0.85,
        )
        db.add(company)
        db.flush()
    for name in [data.name, *data.aliases]:
        norm = normalized_name(name)
        if not db.first(CompanyAlias, company_id=company.id, normalized_name=norm, country=country):
            db.add(
                CompanyAlias(
                    company_id=company.id,
                    name=name,
                    normalized_name=norm,
                    country=country,
                    confidence=1 if domain else 0.85,
                )
            )
            db.flush()
    from leados.storage.records import now

    company.last_seen_at = now()
    return company, created


def detect_signals(snippet: str, catalog: dict[str, SignalDefinition], *, live: bool = False) -> list[str]:
    text = re.sub(r"\s+", " ", snippet).casefold()
    matches = []
    event = (
        r"\b(?:hiring|hires|recruiting|recruits|appointed|appoints|vacancy|vacancies|looking for|seeking)\b"
    )
    live_roles = {
        "DPO_HIRING": r"\b(?:data protection officer|dpo)\b",
        "CONTRACT_MANAGER_HIRING": r"\bcontract manager\b",
        "LEGAL_OPS_HIRING": r"\b(?:head of legal operations|legal operations head|legal operations lead)\b",
        "THIRD_PARTY_RISK_HIRING": r"\bthird[ -]party risk manager\b",
    }
    negated_event = live and any(
        term in text for term in ["not hiring", "no vacancy", "not appointing", "event denied"]
    )
    # Deterministic mock matching intentionally requires a concrete catalog event phrase.
    # Negated statements and completed programmes do not create an opportunity.
    for sid, signal in catalog.items():
        if negated_event or any(term.casefold() in text for term in signal.disqualifiers):
            continue
        if any(
            re.search(r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)", text) for term in signal.keywords
        ):
            matches.append(sid)
        elif live and sid in live_roles:
            role = live_roles[sid]
            if re.search(event + r".{0,180}?" + role, text) or re.search(role + r".{0,120}?" + event, text):
                matches.append(sid)
    if live:
        from leados.qualification import DEMAND, DEMAND_SIGNALS, SCOPES

        if re.search(DEMAND, text):
            matches.extend(
                DEMAND_SIGNALS[vid]
                for vid, scope in SCOPES.items()
                if re.search(scope, text) and DEMAND_SIGNALS[vid] in catalog
            )
    return list(dict.fromkeys(matches))


def route_verticals(signal: SignalDefinition) -> list[dict]:
    return [
        {"vertical_id": vid, "rank": i + 1, "match": 1 if i == 0 else 0.8}
        for i, vid in enumerate(signal.vertical_ids)
    ]


def recency_factor(event_date: date | None, as_of: date, rules: dict) -> float:
    if event_date is None or event_date > as_of:
        return 0
    age = (as_of - event_date).days
    return next(row["factor"] for row in rules["recency"] if age <= row["max_days"])


def score_opportunity(
    signal: SignalDefinition,
    vertical_id: str,
    company: Company,
    evidence: list[Evidence],
    research: dict,
    knowledge: Knowledge,
    as_of: date,
) -> dict:
    rules = knowledge.scoring
    vertical = knowledge.verticals[vertical_id]
    quality = max((e.confidence for e in evidence if e.company_match and not e.conflict), default=0)
    fit = 1 if company.sector in vertical.typical_client else 0.6
    commercial = research.get("qualification", {})
    factors = {
        "identifiable_need": research["need"],
        "icp_fit": fit,
        "trigger_strength": commercial.get(
            "signal_confidence", signal.base_strength / rules["signal_strength_max"]
        ),
        "trigger_recency": recency_factor(evidence[0].published_date if evidence else None, as_of, rules),
        "mandate_value": research["mandate_value"],
        "buyer_reachability": (0.2 if commercial else 0.6) if vertical.buyer_roles else 0,
        "expertise_match": 1 if vertical_id in signal.vertical_ids else 0,
        "evidence_quality": quality,
    }
    rationales = {
        "identifiable_need": "Catalog need intensity; a hypothesis, not confirmed demand",
        "icp_fit": f"Sector {company.sector}: {'core' if fit == 1 else 'adjacent'} ICP",
        "trigger_strength": f"Signal weight {signal.base_strength}/25 normalized to 20; never added directly",
        "trigger_recency": "Published event age under the versioned recency decay schedule",
        "mandate_value": "Scope assessment; no confirmed budget",
        "buyer_reachability": "Role mapped only; no verified personal contact",
        "expertise_match": "Event maps to a defined Novation vertical",
        "evidence_quality": "Best non-conflicting, company-matched source confidence",
    }
    if commercial:
        rationales["identifiable_need"] = (
            "Documented external requirement, capped at 0.75; budget and engagement unconfirmed"
        )
        rationales["trigger_strength"] = (
            "Separate signal confidence after commercial gates, not a search relevance score"
        )
        rationales["buyer_reachability"] = "Buyer role only; no verified reachable person"
    parts = {
        key: {
            "points": int(maximum * min(1, max(0, factors[key])) + 0.5),
            "maximum": maximum,
            "rationale": rationales[key],
        }
        for key, maximum in rules["components"].items()
    }
    total = sum(p["points"] for p in parts.values())
    band = score_band(total, rules)
    from leados.qualification import SCORE_VERSION

    return {
        "score": total,
        "score_band": band,
        "components": parts,
        "score_version": SCORE_VERSION if commercial else rules["version"],
        "inputs": {
            "factors": factors,
            "as_of": str(as_of),
            "qualification_version": commercial.get("version"),
            "evidence_ids": [e.id for e in evidence],
            "evidence_hashes": {e.id: e.content_hash for e in evidence},
            "weights": dict(rules["components"]),
            "timing_basis": "SOURCE_PUBLICATION_DATE",
            "signal_id": signal.signal_id,
            "vertical_id": vertical_id,
        },
    }


def audit_evidence(
    evidence: list[Evidence],
    signal: SignalDefinition,
    as_of: date,
    claims: list[dict],
    knowledge: Knowledge,
    *,
    live: bool = False,
) -> tuple[AuditStatus, list[str], float]:
    if not evidence or not any(e.snippet.strip() for e in evidence):
        return AuditStatus.INSUFFICIENT_EVIDENCE, ["No supporting content"], 0
    reasons = []
    if not any(e.company_match for e in evidence):
        return AuditStatus.REJECTED, ["Source describes a different company"], 0
    if any(e.conflict for e in evidence):
        reasons.append("Conflicting source assertions require review")
    qualified = [
        e
        for e in evidence
        if e.company_match
        and not e.conflict
        and e.confidence >= signal.source_reliability_requirement
        and e.published_date is not None
        and e.published_date <= as_of
        and signal.signal_id in detect_signals(e.snippet, {signal.signal_id: signal}, live=live)
    ]
    if not qualified:
        reasons.append("No dated, reliable, matching evidence for this event")
    if not any(e.assertion_type == "FACT" for e in qualified):
        reasons.append("Allegation or interpretation requires fact verification before outreach")
    ids = {e.id for e in evidence}
    if any(not c.get("evidence_ids") or not set(c["evidence_ids"]).issubset(ids) for c in claims):
        reasons.append("Claim has missing or unrelated evidence references")
    if any(not e.published_date or e.published_date > as_of for e in evidence) and (
        not live or not qualified
    ):
        reasons.append("Missing or future publication date")
    confidence = max((e.confidence for e in qualified), default=0)
    if reasons:
        return AuditStatus.NEEDS_RESEARCH, reasons, min(confidence, 0.69)
    # High confidence is only possible after all evidence checks pass.
    return AuditStatus.VERIFIED, [], confidence
