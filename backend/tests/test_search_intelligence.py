from leados.services.search_intelligence import (
    determine_icp_profile,
    compute_search_intelligence,
    ICP_PROFILES,
)


def test_determine_icp_profiles():
    # Test ICP-S1 (DPDP / Privacy)
    s1 = determine_icp_profile(
        "Fintech Corp",
        "Fintech",
        "Company launches consumer mobile lending app and needs DPDP Act 2023 readiness assessment.",
    )
    assert s1["code"] == "ICP-S1"
    assert "DPDP" in s1["name"]

    # Test ICP-S2 (Contract / CLM)
    s2 = determine_icp_profile(
        "SaaS Enterprise",
        "Enterprise Software",
        "Enterprise issues RFP for contract lifecycle management CLM review and backlog remediation.",
    )
    assert s2["code"] == "ICP-S2"
    assert "Contract" in s2["name"]

    # Test ICP-L1 (White-Collar / Investigations)
    l1 = determine_icp_profile(
        "Promoter Holdings",
        "Financial Services",
        "SEBI issued show cause notice regarding financial irregularity and statutory auditor resignation.",
    )
    assert l1["code"] == "ICP-L1"
    assert "White-Collar" in l1["name"]

    # Test ICP-L2 (Commercial Disputes)
    l2 = determine_icp_profile(
        "Industrial Logistics",
        "Manufacturing",
        "Company initiates commercial arbitration and NCLT proceedings over ₹5 crore unpaid receivables.",
    )
    assert l2["code"] == "ICP-L2"
    assert "Disputes" in l2["name"]


def test_compute_search_intelligence_factors_and_outreach():
    candidate = {
        "company": {"name": "NABARD", "domain": "nabard.org", "sector": "Banking & Finance", "country": "India"},
        "source_url": "https://nabard.org/tenders/dpdp-rfp",
        "title": "REQUEST FOR PROPOSAL (RFP) FOR Consultant for Implementation of DPDP Act 2023",
        "snippet": "NABARD invites bids for selection of a consultant for DPDP Act 2023 gap assessment and privacy framework implementation.",
        "published_date": "2026-10-01",
        "confidence": 0.85,
    }

    qualification = {
        "service_demand": True,
        "vertical_ids": ["privacy"],
        "evidence_confidence": 0.85,
    }

    intel = compute_search_intelligence(None, candidate, qualification)

    # 1. Check ICP profile match
    assert intel["icp_profile"]["code"] == "ICP-S1"

    # 2. Check all 8 deterministic factors exist
    factors = intel["factors"]
    assert "identifiable_need" in factors
    assert "icp_fit" in factors
    assert "trigger_strength" in factors
    assert "trigger_recency" in factors
    assert "mandate_value" in factors
    assert "buyer_reachability" in factors
    assert "expertise_match" in factors
    assert "evidence_quality" in factors

    # Weights must sum to 100
    total_weights = sum(f["weight"] for f in factors.values())
    assert total_weights == 100

    # Total score must equal sum of factor scores
    assert intel["total_factor_score"] == sum(f["score"] for f in factors.values())
    assert intel["total_factor_score"] >= 80
    assert intel["score_band"] == "HOT"

    # 3. Check why_searched rationale
    assert "NABARD" in intel["why_searched"]
    assert "ICP-S1" in intel["why_searched"]

    # 4. Check outreach mail package
    outreach = intel["outreach"]
    assert len(outreach["target_roles"]) > 0
    assert "General Counsel" in outreach["target_roles"] or "Data Protection Officer" in outreach["target_roles"]
    assert "legal@nabard.org" in outreach["target_email"]
    assert len(outreach["subject_options"]) >= 2
    assert "NABARD" in outreach["draft_email"]
    assert "DPDP" in outreach["draft_email"]
    assert "[Draft prepared for human review; no automated email sent]" in outreach["draft_email"]
