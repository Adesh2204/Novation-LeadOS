"""Comprehensive intelligence module for searched companies in live discovery.

Evaluates candidates strictly against:
1. The 4 ICP Profiles from Section 3 of the Novation Playbook (ICP-L1, ICP-L2, ICP-S1, ICP-S2).
2. The 8 deterministic scoring factors from Section 7 of the Novation Playbook (Need 25, ICP fit 20, Trigger 20, Recency 10, Mandate value 10, Reachability 5, Expertise 5, Evidence 5 = 100).
3. Complete personalized outreach mail package (subjects, full draft email, decision-maker roles, contact email, strategy).
"""

import re
from datetime import UTC, date, datetime
from typing import Any

from leados.engine import detect_signals
from leados.knowledge import knowledge
from leados.qualification import SCOPES
from leados.storage.base import StorageProvider
from leados.storage.records import (
    Company,
    DecisionMakerRole,
    Opportunity,
    OpportunityEvidence,
    OutreachDraft,
    Service,
    SourceDocument,
)

# Canonical 4 ICP Profiles from Novation Playbook Section 3
ICP_PROFILES = {
    "ICP-S1": {
        "code": "ICP-S1",
        "name": "DPDP & Privacy Implementation",
        "vertical_ids": ["privacy", "ai_governance", "vendor_governance"],
        "default_service": "DPDP Readiness Assessment",
        "default_vertical": "Privacy & Data Protection",
        "buyer_roles": [
            "General Counsel",
            "Data Protection Officer (DPO)",
            "Chief Information Security Officer (CISO)",
            "Head of Compliance",
        ],
        "summary": "Companies collecting significant personal data with India operations and DPDP compliance exposure.",
        "match_indicators": [
            "Active India operations in digital, consumer, SaaS, or financial services",
            "Processes personal data of Indian residents requiring DPDP Act 2023 compliance",
            "Outdated privacy documentation, vendor gaps, or tender for external DPDP assessment",
        ],
    },
    "ICP-S2": {
        "code": "ICP-S2",
        "name": "Contract Lifecycle Management (CLM)",
        "vertical_ids": ["clm", "legal_operations", "technology_ip"],
        "default_service": "Contract Lifecycle Management (CLM)",
        "default_vertical": "Contract Lifecycle Management",
        "buyer_roles": [
            "General Counsel",
            "Head of Legal Operations",
            "Head of Procurement",
            "VP Sales Operations",
        ],
        "summary": "High contracting volume, expanding vendor/customer ecosystem, and potential CLM / legal-ops requirements.",
        "match_indicators": [
            "Rapid business expansion with large sales or vendor ecosystem in India",
            "High contract volume leading to review backlogs or repository fragmentation",
            "Procurement transformation or requirement for external contract remediation",
        ],
    },
    "ICP-L1": {
        "code": "ICP-L1",
        "name": "White-Collar & Regulatory Investigations",
        "vertical_ids": ["investigations_disputes", "corporate_compliance"],
        "default_service": "White-Collar Defense & Regulatory Advisory",
        "default_vertical": "Investigations & Disputes Support",
        "buyer_roles": [
            "Founder / Managing Director",
            "Chief Financial Officer (CFO)",
            "General Counsel",
            "Board Audit Committee",
        ],
        "summary": "₹100 Cr to ₹5,000 Cr+ India operations, promoter-driven or regulated business with regulatory or governance exposure.",
        "match_indicators": [
            "Regulatory proceedings or statutory inquiries (SEBI, SFIO, ED, MCA)",
            "Financial irregularity, forensic audit requirement, or auditor resignation",
            "High-stakes compliance or management exposure requiring independent advisory",
        ],
    },
    "ICP-L2": {
        "code": "ICP-L2",
        "name": "Commercial Disputes & Arbitration",
        "vertical_ids": ["investigations_disputes", "transaction_integration", "clm"],
        "default_service": "Commercial Arbitration & Dispute Strategy",
        "default_vertical": "Investigations & Disputes Support",
        "buyer_roles": [
            "General Counsel",
            "Head of Legal",
            "Chief Financial Officer (CFO)",
            "Managing Director",
        ],
        "summary": "₹1 Cr+ unpaid receivables, distributor termination, shareholder/vendor disputes, IBC/NCLT proceedings, or commercial litigation.",
        "match_indicators": [
            "Significant unpaid receivables, contract termination, or supplier disputes",
            "Commercial litigation, arbitration announcements, or tribunal proceedings",
            "Formal dispute management or pre-litigation settlement support required",
        ],
    },
}

FALLBACK_VERTICAL_PROFILES = {
    "corporate_compliance": {
        "code": "ICP-C1",
        "name": "Corporate Compliance & Entity Coordination",
        "default_service": "Entity Governance & Statutory Compliance",
        "default_vertical": "Corporate Compliance & Entity Coordination",
        "buyer_roles": ["Company Secretary", "General Counsel", "Head of Compliance", "CFO"],
        "summary": "Multi-entity Indian operations requiring secretarial coordination, MCA filings, and statutory compliance.",
    },
    "ai_governance": {
        "code": "ICP-A1",
        "name": "Responsible AI & Algorithm Governance",
        "default_service": "AI Governance Framework & Risk Assessment",
        "default_vertical": "AI Governance",
        "buyer_roles": ["Chief Technology Officer (CTO)", "General Counsel", "CISO", "Head of AI"],
        "summary": "Enterprise deploying AI / machine learning requiring governance frameworks, oversight policies, and risk assessments.",
    },
    "vendor_governance": {
        "code": "ICP-V1",
        "name": "Third-Party & Vendor Risk Governance",
        "default_service": "Vendor Risk Assessment & Governance",
        "default_vertical": "Vendor & Third-Party Governance",
        "buyer_roles": ["Head of Procurement", "CISO", "Chief Risk Officer", "General Counsel"],
        "summary": "Extensive vendor network requiring independent supplier assessments, onboarding controls, and audit support.",
    },
    "technology_ip": {
        "code": "ICP-T1",
        "name": "Technology Contracting & IP Advisory",
        "default_service": "Software Licensing & Tech Contracting",
        "default_vertical": "Technology Contracts & IP",
        "buyer_roles": ["General Counsel", "CTO", "VP Engineering", "Head of Licensing"],
        "summary": "Tech-enabled business requiring licensing frameworks, intellectual property advisory, and SaaS agreements.",
    },
    "legal_operations": {
        "code": "ICP-O1",
        "name": "Legal Operations & Spend Optimization",
        "default_service": "Legal Operations & Spend Review",
        "default_vertical": "Legal Operations",
        "buyer_roles": ["General Counsel", "Head of Legal Operations", "CFO"],
        "summary": "Corporate legal department managing high caseloads, outside counsel spend, and workflow bottlenecks.",
    },
    "transaction_integration": {
        "code": "ICP-M1",
        "name": "Transaction Diligence & Post-Merger Integration",
        "default_service": "Transaction Diligence & Integration Legal Support",
        "default_vertical": "Transaction Diligence & Integration",
        "buyer_roles": ["Chief Strategy Officer", "General Counsel", "Head of M&A", "CFO"],
        "summary": "Company executing M&A, investment, or corporate restructuring requiring legal due diligence and integration support.",
    },
}


def _clean_text(val: Any) -> str:
    return str(val or "").strip()


def determine_icp_profile(
    company_name: str,
    sector: str,
    text: str,
    vertical_id: str | None = None,
) -> dict[str, Any]:
    """Matches candidate against the 4 core Playbook ICP profiles."""
    haystack = f"{company_name} {sector} {text}".casefold()

    # 1. Check ICP-S1 (DPDP / Privacy)
    privacy_terms = ["dpdp", "privacy", "data protection", "dpo", "personal data", "dpia", "gdpr", "consent"]
    if any(term in haystack for term in privacy_terms) or vertical_id == "privacy":
        return {
            **ICP_PROFILES["ICP-S1"],
            "matched_via": "DPDP / personal data compliance requirements detected",
        }

    # 2. Check ICP-L1 (White-Collar / Investigations / Regulated)
    white_collar_terms = [
        "sebi", "sfio", "ed investigation", "enforcement directorate", "show cause",
        "promoter dispute", "fir", "eow", "auditor resignation", "financial irregularity",
        "forensic audit", "fraud", "whistleblower", "director change", "mca filing",
    ]
    if any(term in haystack for term in white_collar_terms):
        return {
            **ICP_PROFILES["ICP-L1"],
            "matched_via": "Regulatory enforcement, investigation, or governance trigger detected",
        }

    # 3. Check ICP-L2 (Commercial Disputes)
    dispute_terms = [
        "arbitration", "receivables", "nclt", "ibc", "insolvency", "litigation",
        "contract termination", "distributor dispute", "vendor dispute", "shareholder dispute",
    ]
    if any(term in haystack for term in dispute_terms):
        return {
            **ICP_PROFILES["ICP-L2"],
            "matched_via": "Commercial dispute, tribunal, or arbitration signal detected",
        }

    # 4. Check ICP-S2 (Contract / CLM)
    clm_terms = [
        "clm", "contract review", "contract lifecycle", "contract manager", "procurement rfp",
        "contract backlog", "tender", "request for proposal", "licensing agreement", "secretarial",
    ]
    if any(term in haystack for term in clm_terms) or vertical_id in {"clm", "legal_operations"}:
        return {
            **ICP_PROFILES["ICP-S2"],
            "matched_via": "High contracting volume, procurement RFP, or CLM requirement detected",
        }

    # Fallback to vertical-specific profile if known
    if vertical_id and vertical_id in FALLBACK_VERTICAL_PROFILES:
        fallback = FALLBACK_VERTICAL_PROFILES[vertical_id]
        return {
            "code": fallback["code"],
            "name": fallback["name"],
            "vertical_ids": [vertical_id],
            "default_service": fallback["default_service"],
            "default_vertical": fallback["default_vertical"],
            "buyer_roles": fallback["buyer_roles"],
            "summary": fallback["summary"],
            "match_indicators": [
                f"Operational requirements align with Novation's {fallback['default_vertical']} vertical",
                f"Service demand mapped to {fallback['default_service']}",
            ],
            "matched_via": f"Matched through vertical service scope ({vertical_id})",
        }

    # Default to ICP-S1 if general compliance
    return {
        **ICP_PROFILES["ICP-S1"],
        "matched_via": "Default enterprise compliance profile applied",
    }


def compute_search_intelligence(
    db: StorageProvider | None,
    candidate: dict[str, Any],
    qualification: dict[str, Any] | None = None,
    opportunity_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Generates the factor breakdown, why searched rationale, and outreach mail for any searched company."""
    company_dict = candidate.get("company", {}) if isinstance(candidate.get("company"), dict) else {}
    company_name = company_dict.get("name") or candidate.get("company") or "Discovered Enterprise"
    domain = company_dict.get("domain") or candidate.get("domain") or ""
    sector = company_dict.get("sector") or candidate.get("industry") or "Corporate Enterprise"
    country = company_dict.get("country") or "India"
    snippet = _clean_text(candidate.get("snippet"))
    title = _clean_text(candidate.get("title") or candidate.get("source_name") or "Public Notice")
    source_url = candidate.get("source_url") or ""
    published_date_str = candidate.get("published_date")

    # If an existing opportunity is linked, use its authoritative data
    existing_opp: Opportunity | None = None
    existing_draft: OutreachDraft | None = None
    existing_contacts: list[dict[str, Any]] = []
    if db and opportunity_ids:
        for oid in opportunity_ids:
            opp = db.get(Opportunity, oid)
            if opp:
                existing_opp = opp
                draft = db.first(OutreachDraft, opportunity_id=opp.id)
                if draft:
                    existing_draft = draft
                roles = db.list(DecisionMakerRole, opportunity_id=opp.id)
                for r in roles:
                    existing_contacts.append({
                        "person_name": r.person_name or "Decision Maker",
                        "role": r.role,
                        "contact_email": r.contact_email or f"legal@{domain or 'company.com'}",
                        "contact_status": r.contact_status or "RECOMMENDED_ROLE",
                    })
                break

    # Determine vertical and service
    vertical_id = None
    if existing_opp:
        vertical_id = existing_opp.vertical_id
    elif qualification and qualification.get("vertical_ids"):
        vertical_id = qualification["vertical_ids"][0]
    else:
        # Detect from signals
        sig_ids = detect_signals(snippet, knowledge.signals, live=True)
        if sig_ids:
            first_sig = knowledge.signals.get(sig_ids[0])
            if first_sig and first_sig.vertical_ids:
                vertical_id = first_sig.vertical_ids[0]

    # Map ICP profile
    icp = determine_icp_profile(company_name, sector, f"{title} {snippet}", vertical_id)

    # Determine vertical definition
    actual_vid = vertical_id or (icp["vertical_ids"][0] if icp.get("vertical_ids") else "privacy")
    v_def = knowledge.verticals.get(actual_vid)
    vertical_name = v_def.name if v_def else icp.get("default_vertical", "Privacy & Data Protection")

    if existing_opp:
        service_rec = db.get(Service, existing_opp.service_id) if db else None
        service_name = service_rec.name if service_rec else existing_opp.trigger
    elif v_def and v_def.services:
        service_name = v_def.services[0]
    else:
        service_name = icp.get("default_service", "DPDP Readiness Assessment")

    # Buyer roles
    opp_roles = (
        [r.role for r in db.list(DecisionMakerRole, opportunity_id=existing_opp.id)]
        if db and existing_opp
        else []
    )
    buyer_roles = (
        opp_roles
        if opp_roles
        else v_def.buyer_roles
        if v_def and v_def.buyer_roles
        else icp.get("buyer_roles", ["General Counsel", "Head of Legal", "Compliance Officer"])
    )

    # Recency evaluation
    event_date: date | None = None
    if published_date_str:
        try:
            event_date = date.fromisoformat(str(published_date_str)[:10])
        except Exception:
            event_date = None

    now_date = date.today()
    days_old = (now_date - event_date).days if event_date else None

    # Calculate the 8 Factors strictly according to Section 7 of Playbook:
    # 1. Identifiable Legal / Compliance Need (25 pts)
    # 2. ICP / Company Fit (20 pts)
    # 3. Trigger Strength (20 pts)
    # 4. Trigger Recency (10 pts)
    # 5. Potential Mandate Value (10 pts)
    # 6. Ability to Reach Decision-Maker (5 pts)
    # 7. Novation Expertise Match (5 pts)
    # 8. Evidence Quality & Provenance (5 pts)

    is_tender_or_rfp = bool(re.search(r"\b(rfp|tender|request for proposal|expression of interest|eoi|procurement|bids?)\b", f"{title} {snippet}", re.IGNORECASE))
    is_regulatory_action = bool(re.search(r"\b(sebi|sfio|investigation|show cause|notice|order|filing|tribunal|nclt)\b", f"{title} {snippet}", re.IGNORECASE))
    has_verified_demand = bool(qualification and qualification.get("service_demand"))

    # Factor 1: Identifiable legal/compliance need (25 pts)
    if is_tender_or_rfp or has_verified_demand:
        need_pts = 24
        need_status = "DOCUMENTED_REQUIREMENT"
        need_detail = f"Explicit public requirement for external {service_name} or advisory services."
    elif is_regulatory_action:
        need_pts = 22
        need_status = "STATUTORY_EXPOSURE"
        need_detail = "Active regulatory proceeding or compliance disclosure creating urgent advisory need."
    elif any(term in snippet.casefold() for term in ["hiring", "appointed", "vacancy", "backlog"]):
        need_pts = 17
        need_status = "OPERATIONAL_TRIGGER"
        need_detail = "Organizational expansion or internal capability hiring indicates operational need."
    else:
        need_pts = 14
        need_status = "MARKET_OPPORTUNITY"
        need_detail = f"Market business event creates potential requirement for {service_name}."

    # Factor 2: ICP / company fit (20 pts)
    is_india = "india" in f"{country} {snippet}".casefold() or True  # Catalog is India-targeted
    sector_fit = 1.0 if (v_def and any(s.casefold() in sector.casefold() for s in v_def.typical_client)) else 0.8
    if is_india and sector_fit == 1.0:
        fit_pts = 19
        fit_status = "CORE_ICP_MATCH"
        fit_detail = f"Indian operating company in {sector}, directly matching core {icp['name']} profile."
    elif is_india:
        fit_pts = 16
        fit_status = "ADJACENT_ICP_MATCH"
        fit_detail = f"Indian operating enterprise ({sector}); adjacent sector with active commercial footprint."
    else:
        fit_pts = 12
        fit_status = "REQUIRES_VERIFICATION"
        fit_detail = "Enterprise operates in relevant sector; local India entity requires verification."

    # Factor 3: Trigger strength (20 pts)
    if is_tender_or_rfp:
        trigger_pts = 19
        trigger_status = "HIGH_STRENGTH"
        trigger_detail = "Published procurement notice / RFP with explicit scope and commercial intent."
    elif is_regulatory_action:
        trigger_pts = 18
        trigger_status = "HIGH_STRENGTH"
        trigger_detail = "Official regulatory notice or statutory action with immediate legal impact."
    elif has_verified_demand:
        trigger_pts = 17
        trigger_status = "VERIFIED_DEMAND"
        trigger_detail = "Documented demand excerpt connecting commercial trigger to service scope."
    else:
        trigger_pts = 14
        trigger_status = "QUALIFIED_SIGNAL"
        trigger_detail = "Identifiable market announcement with clear relevance to corporate practice areas."

    # Factor 4: Trigger recency (10 pts)
    if days_old is not None and days_old <= 7:
        recency_pts = 10
        recency_status = "IMMEDIATE (<7D)"
        recency_detail = f"Published {days_old} days ago; maximum responsiveness window."
    elif days_old is not None and days_old <= 30:
        recency_pts = 8
        recency_status = "RECENT (<30D)"
        recency_detail = f"Published {days_old} days ago; within active 30-day BD outreach cycle."
    elif days_old is not None and days_old <= 90:
        recency_pts = 5
        recency_status = "TIMELY (<90D)"
        recency_detail = f"Published {days_old} days ago; within quarterly review window."
    else:
        recency_pts = 3
        recency_status = "AGE_UNCONFIRMED"
        recency_detail = "Publication date unconfirmed or older notice; verify active status during review."

    # Factor 5: Potential mandate value (10 pts)
    if is_tender_or_rfp or is_regulatory_action:
        value_pts = 9
        value_status = "ENTERPRISE_MANDATE"
        value_detail = "Substantial enterprise advisory or multi-month execution mandate value."
    else:
        value_pts = 7
        value_status = "STRATEGIC_ENGAGEMENT"
        value_detail = "Specialized project engagement scope with ongoing advisory potential."

    # Factor 6: Decision-maker reachability (5 pts)
    reach_pts = 4
    reach_status = "ROLES_IDENTIFIED"
    reach_detail = f"Primary buyer roles defined: {', '.join(buyer_roles[:2])}."

    # Factor 7: Novation expertise match (5 pts)
    expertise_pts = 5
    expertise_status = "DIRECT_EXPERTISE"
    expertise_detail = f"Directly serviced by Novation {vertical_name} practice team."

    # Factor 8: Evidence quality (5 pts)
    evidence_conf = float(candidate.get("confidence") or (qualification.get("evidence_confidence") if qualification else 0.7) or 0.7)
    if evidence_conf >= 0.75:
        evidence_pts = 5
        evidence_status = "HIGH_CONFIDENCE"
        evidence_detail = f"Verifiable source URL with direct factual snippet ({int(evidence_conf * 100)}% confidence)."
    elif evidence_conf >= 0.5:
        evidence_pts = 4
        evidence_status = "VERIFIED_SOURCE"
        evidence_detail = f"Public announcement citation confirmed ({int(evidence_conf * 100)}% confidence)."
    else:
        evidence_pts = 3
        evidence_status = "REQUIRES_REVIEW"
        evidence_detail = "Preliminary source excerpt; human source audit advised."

    total_score = need_pts + fit_pts + trigger_pts + recency_pts + value_pts + reach_pts + expertise_pts + evidence_pts

    if total_score >= 80:
        score_band = "HOT"
    elif total_score >= 65:
        score_band = "STRONG"
    elif total_score >= 50:
        score_band = "MONITOR"
    else:
        score_band = "LOW"

    factors = {
        "identifiable_need": {
            "name": "Identifiable Legal / Compliance Need",
            "weight": 25,
            "score": need_pts,
            "status": need_status,
            "detail": need_detail,
        },
        "icp_fit": {
            "name": "ICP & Company Profile Fit",
            "weight": 20,
            "score": fit_pts,
            "status": fit_status,
            "detail": fit_detail,
        },
        "trigger_strength": {
            "name": "Trigger Strength & Event",
            "weight": 20,
            "score": trigger_pts,
            "status": trigger_status,
            "detail": trigger_detail,
        },
        "trigger_recency": {
            "name": "Trigger Recency & Freshness",
            "weight": 10,
            "score": recency_pts,
            "status": recency_status,
            "detail": recency_detail,
        },
        "mandate_value": {
            "name": "Potential Mandate Value",
            "weight": 10,
            "score": value_pts,
            "status": value_status,
            "detail": value_detail,
        },
        "buyer_reachability": {
            "name": "Decision-Maker Reachability",
            "weight": 5,
            "score": reach_pts,
            "status": reach_status,
            "detail": reach_detail,
        },
        "expertise_match": {
            "name": "Novation Expertise Match",
            "weight": 5,
            "score": expertise_pts,
            "status": expertise_status,
            "detail": expertise_detail,
        },
        "evidence_quality": {
            "name": "Evidence Quality & Provenance",
            "weight": 5,
            "score": evidence_pts,
            "status": evidence_status,
            "detail": evidence_detail,
        },
    }

    # Synthesize "Why Exactly This Company Was Searched"
    trigger_brief = title if len(title) > 10 else snippet[:160]
    why_searched = (
        f"Searched under {icp['code']} ({icp['name']}): {company_name} was identified through a targeted scan "
        f"for Indian enterprise {service_name.lower()} requirements. The company exhibits clear ICP markers ({sector}, India operations) "
        f"alongside an active trigger: \"{trigger_brief[:140]}...\". This directly aligns with Novation's specialized {vertical_name} practice, "
        f"achieving a deterministic factor score of {total_score}/100 ({score_band})."
    )

    # Build Personalized Outreach Mail Package
    primary_buyer = buyer_roles[0] if buyer_roles else "General Counsel"
    clean_domain = re.sub(r"^https?://(www\.)?", "", domain).split("/")[0] if domain else ""
    target_email = (
        existing_contacts[0]["contact_email"]
        if existing_contacts and existing_contacts[0].get("contact_email")
        else f"legal@{clean_domain}" if clean_domain else f"legal@{re.sub(r'[^a-z0-9]', '', company_name.casefold())}.com"
    )

    # Subject options
    subject_options = [
        f"{company_name}: {service_name} Advisory — Novation Strategy",
        f"Assisting {company_name} regarding {service_name.lower()}",
        f"Strategic consultation regarding {company_name}'s recent announcement",
    ]

    # Snippet quote for draft
    clean_snippet = re.sub(r"\s+", " ", snippet).strip()
    excerpt_quote = clean_snippet[:220] if len(clean_snippet) > 20 else title

    if existing_draft and existing_draft.body:
        draft_email = existing_draft.body
        if existing_draft.subjects:
            subject_options = existing_draft.subjects
    else:
        draft_email = (
            f"Dear {primary_buyer} / Leadership Team,\n\n"
            f"I am writing regarding {company_name}'s recent announcement: \"{excerpt_quote}...\".\n\n"
            f"Novation Strategy specializes in {service_name}, supporting leading organizations in managing "
            f"high-stakes compliance, contract governance, and legal execution across India.\n\n"
            f"Given your current focus on this requirement, our team can provide tailored advisory and execution "
            f"support to ensure seamless adherence and operational rigor without creating an internal team backlog.\n\n"
            f"Would you or your team have 15 minutes next week for a brief introductory conversation to explore how "
            f"Novation can assist {company_name}?\n\n"
            f"Best regards,\n"
            f"Novation Strategy\n"
            f"Lead Intelligence Desk\n\n"
            f"[Draft prepared for human review; no automated email sent]"
        )

    outreach_angle = (
        f"Engage through {primary_buyer} focusing on strategic relief for {service_name}. "
        f"Lead with the verified public requirement and position Novation as an execution partner that absorbs "
        f"the regulatory and contracting burden without overhead."
    )

    return {
        "company": company_name,
        "domain": clean_domain,
        "sector": sector,
        "country": country,
        "icp_profile": {
            "code": icp["code"],
            "name": icp["name"],
            "summary": icp["summary"],
            "match_reasons": icp.get("match_indicators", []),
            "matched_via": icp.get("matched_via", "Playbook ICP criteria"),
        },
        "why_searched": why_searched,
        "total_factor_score": total_score,
        "score_band": score_band,
        "factors": factors,
        "outreach": {
            "target_roles": buyer_roles,
            "target_email": target_email,
            "contacts": existing_contacts,
            "subject_options": subject_options,
            "draft_email": draft_email,
            "outreach_angle": outreach_angle,
            "recommended_service": service_name,
            "vertical_name": vertical_name,
        },
        "trigger_summary": title or snippet[:150],
        "published_date": published_date_str,
        "source_url": source_url,
    }
