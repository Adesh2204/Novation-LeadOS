"""Conservative commercial gates. Topic relevance never establishes purchasing intent."""

import re
from datetime import date
from typing import Any

QUALIFICATION_VERSION = "buyer-demand-2.0.0"
SCORE_VERSION = "1.1.0-commercial-gates"
# Each scope represents a distinct service problem, not a related catalog vertical.
SCOPES = {
    "privacy": r"\b(?:dpdp|privacy|data protection|data inventory|data.flow mapping)\b",
    "clm": r"\b(?:contract review|contract backlog|contract lifecycle|clm|contract management)\b",
    "ai_governance": r"\b(?:ai governance|responsible ai|ai risk|ai policy|ai assessment|ai audit)\b",
    "corporate_compliance": r"\b(?:corporate compliance|entity coordination|secretarial|statutory filing|compliance calendar|entity governance)\b",
    "legal_operations": r"\b(?:legal operations|legal workflow|matter backlog|outside.counsel spend|matter management)\b",
    "vendor_governance": r"\b(?:vendor risk|third.party risk|third.party assessment|supplier governance|vendor assessment|vendor remediation)\b",
    "investigations_disputes": r"\b(?:forensic investigation|investigation support|dispute support|arbitration support|forensic audit)\b",
    "transaction_integration": r"\b(?:due diligence|post.merger integration|transaction diligence|integration legal support)\b",
    "technology_ip": r"\b(?:licensing advice|licensing advisory|technology contracts|intellectual property|software licensing|ip advisory)\b",
}
DEMAND_SIGNALS = {
    "privacy": "PRIVACY_CONTROL_PROGRAMME",
    "clm": "CONTRACT_BACKLOG",
    "ai_governance": "AI_POLICY_PROGRAMME",
    "corporate_compliance": "COMPLIANCE_CALENDAR_GAP",
    "legal_operations": "LEGAL_BACKLOG",
    "vendor_governance": "VENDOR_REMEDIATION",
    "investigations_disputes": "REGULATORY_INVESTIGATION",
    "transaction_integration": "DUE_DILIGENCE_PROJECT",
    "technology_ip": "LICENSING_PROGRAMME",
}
DEMAND = r"\b(?:request for proposal|rfp|expression of interest|tender|invites? (?:bids|proposals)|seeking (?:an? )?(?:external|independent|consulting)|requires? (?:an? )?(?:external|independent)|engag(?:e|ing) (?:an? )?(?:external|independent|consulting))\b"
SELLER = r"\b(?:launch(?:es|ed)?|unveil(?:s|ed)?|introduc(?:es|ed)|offers?|sells?|provides?)\b.{0,160}\b(?:platform|solution|product|software|services to|for customers)\b"
HIRING = r"\b(?:hiring|vacancy|recruiting|job opening|appoints?|appointed|looking for.{0,60}(?:officer|manager|counsel))\b"
NOISE = r"\b(?:access denied|captcha|page not found|this role is gone|position closed|job expired|page is blocked|blocked due to (?:a )?security issue)\b"


def access_restricted(content: str) -> bool:
    return bool(
        re.search(
            r"\b(?:access denied|page is blocked|blocked due to (?:a )?security issue|captcha required)\b",
            content.casefold(),
        )
    )


def company_name_supported(company: dict, text: str) -> bool:
    """Match an explicit full name or supplied alias, tolerating punctuation and a trailing acronym."""
    names = [company.get("name", ""), *company.get("aliases", [])]
    normalized = " ".join(re.findall(r"\w+", text.casefold()))
    for name in names:
        primary = re.sub(r"\s*\([^)]*\)\s*$", "", name)
        needle = " ".join(re.findall(r"\w+", primary.casefold()))
        if len(needle) >= 4 and re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", normalized):
            return True
    return False


def qualify(document: dict[str, Any], as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    company = document.get("company", {})
    name = company.get("name", "")
    text = str(document.get("snippet", ""))
    clean = re.sub(r"\s+", " ", text).casefold()
    base: dict[str, Any] = {
        "version": QUALIFICATION_VERSION,
        "timing_basis": "SOURCE_PUBLICATION_DATE",
        "method": "RULE_BASED",
        "llm_review": "NOT_REQUESTED",
        "human_review": "NOT_REVIEWED",
        "status": "TOPIC_MATCH_ONLY",
        "organization_role": "UNCERTAIN",
        "topic_relevance": bool(any(re.search(scope, clean) for scope in SCOPES.values())),
        "service_demand": False,
        "commercial_fit": "UNVERIFIED",
        "vertical_ids": [],
        "signal_ids": [],
        "demand_evidence": [],
        "evidence_confidence": float(document.get("confidence", 0)),
        "signal_confidence": 0.0,
        "reason": "Topic relevance alone does not establish a service requirement.",
    }
    demand_matches = []
    issuer = bool(
        re.search(
            r"\b(?:issues?|issued|invites?|invited|seeking (?:an? )?(?:external|independent|consulting)|requires? (?:an? )?(?:external|independent)|engaging (?:an? )?(?:external|independent|consulting))\b",
            clean,
        )
    )
    # A source excerpt must connect scope and demand in the same bounded passage.
    for match in re.finditer(DEMAND, clean):
        passage = clean[max(0, match.start() - 180) : match.end() + 350]
        if re.search(r"\b(?:no|not|cancelled|withdrawn)\b.{0,30}" + DEMAND, passage):
            continue
        for vertical, scope in SCOPES.items():
            if re.search(scope, passage):
                demand_matches.append((vertical, text[max(0, match.start() - 180) : match.end() + 350]))
    if re.search(NOISE, clean) or (
        (document.get("crawler_error") or document.get("provenance", {}).get("source_error"))
        and not demand_matches
    ):
        return {
            **base,
            "status": "NEEDS_RESEARCH",
            "reason": "Source is unavailable, closed or access restricted; demand cannot be verified.",
        }
    if re.search(SELLER, clean) and (not re.search(DEMAND, clean) or not issuer):
        return {
            **base,
            "status": "NOT_A_BUYER",
            "organization_role": "SOLUTION_PROVIDER",
            "reason": "NO_QUALIFYING_BUYER_SIGNAL: this event describes selling or launching a solution. Separate purchasing evidence is required.",
        }
    if not demand_matches:
        if re.search(DEMAND, clean):
            return {
                **base,
                "status": "NEEDS_RESEARCH",
                "reason": "Procurement is mentioned; the issuing organization and a suitable Novation service scope require verification.",
            }
        if re.search(r"\b(?:allegation|allegations|denies|rumor|rumour)\b", clean):
            return {
                **base,
                "organization_role": "NEWS_ONLY",
                "reason": "Allegations do not establish verified assistance needs or buyer demand.",
            }
        if re.search(HIRING, clean):
            return {
                **base,
                "status": "NEEDS_RESEARCH",
                "organization_role": "POTENTIAL_BUYER",
                "reason": "Internal hiring is supported; external advisory demand, scope and timing remain unverified.",
            }
        if re.search(
            r"\b(?:acquisition|acquired|merger|backlog|remediation|investigation|incorporat|subsidiary)",
            clean,
        ):
            return {
                **base,
                "status": "NEEDS_RESEARCH",
                "organization_role": "POTENTIAL_BUYER",
                "reason": "A possible operational trigger exists; no documented external service requirement is established.",
            }
        return {
            **base,
            "organization_role": "NEWS_ONLY",
            "reason": "TOPIC_MATCH_ONLY: no concrete buyer requirement is supported by this source.",
        }
    if not issuer:
        return {
            **base,
            "status": "NEEDS_RESEARCH",
            "reason": "A procurement topic is mentioned; the organization issuing a current requirement needs verification.",
        }
    verticals = sorted({v for v, _ in demand_matches})
    base.update(
        service_demand=True,
        organization_role="POTENTIAL_BUYER",
        vertical_ids=verticals,
        signal_ids=[DEMAND_SIGNALS[v] for v in verticals],
        demand_evidence=[{"vertical_id": v, "excerpt": p} for v, p in demand_matches],
    )
    gates = []
    if document.get("crawler_error") or document.get("provenance", {}).get("source_error"):
        gates.append("Source access restricted; demand excerpt requires human review")
    if not name or not document.get("company_match") or not company_name_supported(company, text):
        gates.append("Buyer identity must be supported by the source text")
    if document.get("assertion_type", "FACT") != "FACT" or document.get("conflict"):
        gates.append("Requirement must be a non-conflicting fact, not an allegation or inference")
    if float(document.get("confidence", 0)) < 0.7:
        gates.append("Source reliability needs verification")
    published = document.get("published_date")
    try:
        published = date.fromisoformat(str(published)[:10]) if published else None
    except ValueError:
        published = None
    if not published or published > as_of or (as_of - published).days > 90:
        gates.append("Publication timing is unknown, future or stale")
    # A procurement deadline is used only when explicitly stated; never inferred from publication.
    deadline_match = re.search(r"(?:deadline|closing date|last date)[^\d]{0,30}(\d{4}-\d{2}-\d{2})", clean)
    if deadline_match:
        try:
            deadline = date.fromisoformat(deadline_match.group(1))
            base["deadline"] = deadline.isoformat()
            if deadline < as_of:
                gates.append("Procurement deadline has passed")
        except ValueError:
            gates.append("Procurement deadline requires verification")
    if re.search(r"\b(?:rfp|tender|request for proposal)\b", clean):
        if not deadline_match:
            gates.append("Procurement closing date requires verification")
        if not re.search(
            r"\b(?:eligible|eligibility|qualified (?:firms|bidders)|consulting firms|consultancies invited)\b",
            clean,
        ):
            gates.append("Bidder eligibility requires verification")
    if company.get("sector", "Unknown") == "Unknown" or company.get("country", "Unknown") == "Unknown":
        gates.append("Company sector or country needs ICP verification")
    from leados.knowledge import knowledge

    sector = company.get("sector", "Unknown").casefold()
    if sector != "unknown" and any(
        sector not in {item.casefold() for item in knowledge.verticals[vid].typical_client}
        for vid in verticals
    ):
        gates.append("Adjacent sector requires human ICP fit verification")
    reference = re.search(
        r"(?:tender|rfp|reference)\s+(?:no\.?|number|ref\.?)\s*[:#-]?\s*([a-z0-9][a-z0-9/_-]{2,80})", clean
    )
    base["event_reference"] = reference.group(1) if reference else None
    base["commercial_fit"] = "SUPPORTED" if not gates else "UNVERIFIED"
    base["signal_confidence"] = min(float(document.get("confidence", 0)), 0.69 if gates else 0.85)
    base["status"] = "NEEDS_RESEARCH" if gates else "QUALIFIED_SIGNAL"
    base["reason"] = (
        "; ".join(gates)
        if gates
        else "A dated, company-matched external service requirement supports these specific service scopes; human review is required."
    )
    return base


def source_sufficient(document: dict) -> bool:
    """Sufficiency describes event text; it does not confirm buying intent."""
    return (
        len(document.get("snippet", "")) >= 250
        and bool(document.get("published_date"))
        and bool(document.get("company_match"))
        and not document.get("conflict")
        and float(document.get("confidence", 0)) >= 0.7
        and not re.search(NOISE, document.get("snippet", "").casefold())
    )
