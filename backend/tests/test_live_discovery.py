import hashlib
from unittest.mock import AsyncMock, patch

import pytest

from leados.engine import canonical_url
from leados.providers.cache import ProviderCache
from leados.providers.future.firecrawl import FirecrawlCrawlerProvider
from leados.providers.models import (
    CrawledDocument,
    ProviderBudget,
    SearchResult,
)
from leados.providers.pre_screen import pre_screen_candidate
from leados.services.live_discovery import LiveDiscoveryService


@pytest.fixture(autouse=True)
def clean_cache(tmp_path):
    test_cache = ProviderCache(cache_file=tmp_path / "provider_cache.json")
    with (
        patch("leados.providers.future.firecrawl.provider_cache", test_cache),
        patch("leados.providers.future.exa.provider_cache", test_cache),
        patch("leados.services.live_discovery.provider_cache", test_cache),
        patch("leados.api.provider_cache", test_cache),
    ):
        yield test_cache


# 1. Models & Normalization Tests
def test_search_result_normalization():
    result = SearchResult(
        provider="exa",
        query="privacy officer India",
        title="Flipkart Appoints New DPO",
        url="https://flipkart.com/news/dpo-announcement",
        snippet="Flipkart appoints senior privacy counsel to ensure DPDP compliance.",
        domain="flipkart.com",
        company_hint="Flipkart",
        metadata={"highlights": ["DPDP compliance lead"]},
    )
    assert result.provider == "exa"
    assert result.company_hint == "Flipkart"
    assert result.domain == "flipkart.com"


def test_crawled_document_normalization():
    content = "# About Our Privacy Team\nWe comply with India DPDP Act 2023."
    doc = CrawledDocument(
        url="https://flipkart.com/privacy",
        canonical_url=canonical_url("https://flipkart.com/privacy"),
        title="Flipkart Privacy Policy",
        content=content,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        source_type="company_website",
        provider="firecrawl",
        status="SUCCESS",
    )
    assert doc.status == "SUCCESS"
    assert len(doc.content_hash) == 64
    assert doc.provider == "firecrawl"


# 2. Candidate Pre-Screen & Credit-Safety Gate (Directive 64)
def test_candidate_pre_screen_qualified_vs_unqualified():
    # Qualified candidate: Has recognizable company + privacy/DPO signal keywords
    candidate_qual = {
        "title": "Infosys appoints Data Protection Officer for India DPDP readiness",
        "snippet": "Infosys expands privacy office with new DPO appointment in Bengaluru.",
        "url": "https://infosys.com/news/privacy-officer",
        "company": {"name": "Infosys", "sector": "Information Technology", "country": "India"},
        "published_date": "2026-10-01T00:00:00Z",
    }
    screen_qual = pre_screen_candidate(candidate_qual)
    assert screen_qual.qualifies is True
    assert screen_qual.relevance_score >= 0.70
    assert len(screen_qual.matched_signals) > 0

    # Unqualified candidate: Irrelevant lifestyle / generic text
    candidate_unqual = {
        "title": "Top 10 vacation spots in Goa for corporate offsites",
        "snippet": "Enjoy beautiful beaches and team dinners in South Goa.",
        "url": "https://travelblog.example.com/goa",
        "company": {"name": "Unknown Blog"},
        "published_date": "2026-09-01T00:00:00Z",
    }
    screen_unqual = pre_screen_candidate(candidate_unqual)
    assert screen_unqual.qualifies is False
    assert screen_unqual.relevance_score < 0.70


def test_credit_safety_50_candidates_only_3_qualify():
    """Directive 64: 50 Exa candidates, only 3 qualify. Ensure only 3 pass pre-screen."""
    candidates = []
    # 3 qualifying candidates
    for i in range(3):
        candidates.append(
            {
                "title": f"TechCorp {i} recruits Data Protection Officer and compliance lead",
                "snippet": f"TechCorp {i} announces DPDP compliance hiring and legal operations manager.",
                "url": f"https://techcorp{i}.com/news/hiring",
                "company": {"name": f"TechCorp {i}", "sector": "Enterprise Software", "country": "India"},
            }
        )
    # 47 non-qualifying candidates
    for i in range(47):
        candidates.append(
            {
                "title": f"Generic Article {i} about office interior design trends",
                "snippet": f"Designing open office desks and modern ergonomics for hybrid work {i}.",
                "url": f"https://genericnews.com/article/{i}",
                "company": {"name": f"Generic {i}"},
            }
        )

    qualified = [c for c in candidates if pre_screen_candidate(c).qualifies]
    assert len(qualified) == 3


# 3. ProviderBudget Ceilings & Daily Limits
def test_provider_budget_run_level_limits():
    budget = ProviderBudget(
        max_exa_queries=2,
        max_firecrawl_requests=3,
        max_firecrawl_pages=3,
        max_pages_per_company=2,
    )

    assert budget.can_query_exa() is True
    budget.record_exa_query()
    budget.record_exa_query()
    assert budget.can_query_exa() is False

    assert budget.can_crawl_company("comp1") is True
    budget.record_firecrawl_page("comp1")
    budget.record_firecrawl_page("comp1")
    assert budget.can_crawl_company("comp1") is False  # Hit company page ceiling

    assert budget.can_crawl_page() is True  # 2 of 3 used
    budget.record_firecrawl_page("comp2")
    assert budget.can_crawl_page() is False  # 3 of 3 used


def test_daily_budget_enforcement(clean_cache):
    clean_cache.clear()
    assert clean_cache.check_daily_budget("exa", 2) is True
    clean_cache.record_call("exa")
    clean_cache.record_call("exa")
    assert clean_cache.check_daily_budget("exa", 2) is False


# 4. Cache Behavior & 7-Day TTL (Directive 66)
@pytest.mark.asyncio
async def test_crawl_cache_ttl_and_hit(clean_cache):
    """Directive 66: Same URL requested twice within TTL; second hits cache without calling provider."""
    provider = FirecrawlCrawlerProvider(api_key="test-key", enabled=True, dry_run=False)
    url = "https://acme.com/news/expansion"

    mock_doc = CrawledDocument(
        url=url,
        canonical_url=canonical_url(url),
        title="Acme Expansion",
        content="Acme announces opening Bengaluru office with DPO and Privacy head.",
        content_hash="hash123",
        provider="firecrawl",
        status="SUCCESS",
    )

    with patch.object(provider, "_scrape_safe", AsyncMock(return_value=mock_doc)) as mock_scrape:
        candidate = {
            "title": "Acme appoints DPO for India DPDP",
            "snippet": "Acme expansion with privacy officer",
            "source_url": url,
            "company": {"name": "Acme", "sector": "Cloud", "country": "India"},
        }
        budget = ProviderBudget(max_firecrawl_pages=5)

        # First crawl: calls provider
        res1 = await provider.crawl(candidate, budget=budget)
        assert res1["crawler_status"] == "STAGE_A_CONFIRMED"
        assert mock_scrape.call_count == 1

        # Second crawl: reuses cached document without calling provider
        res2 = await provider.crawl(candidate, budget=budget)
        assert res2["crawler_status"] in ("CACHED", "CACHED_FRESH")
        assert mock_scrape.call_count == 1  # Still 1!


# 5. Early-Exit Behavior (Directive 65)
@pytest.mark.asyncio
async def test_early_exit_behavior(clean_cache):
    """Directive 65: When Stage A provides verified evidence, stop immediately (1 call, not 4)."""
    provider = FirecrawlCrawlerProvider(api_key="test-key", enabled=True, dry_run=False)
    url = "https://zeta.com/announcements/dpo"

    verified_doc = CrawledDocument(
        url=url,
        canonical_url=canonical_url(url),
        title="Zeta appoints Data Protection Officer",
        content="Zeta has formally appointed a Data Protection Officer to lead comprehensive DPDP Act compliance across India.",
        content_hash="hash_zeta_dpo",
        provider="firecrawl",
        status="SUCCESS",
    )

    with patch.object(provider, "_scrape_safe", AsyncMock(return_value=verified_doc)) as mock_scrape:
        candidate = {
            "title": "Zeta recruits Data Protection Officer",
            "snippet": "Zeta names new DPO for DPDP compliance",
            "source_url": url,
            "company": {"name": "Zeta", "sector": "Software", "country": "India", "domain": "zeta.com"},
        }
        budget = ProviderBudget(max_firecrawl_pages=4, max_pages_per_company=4)
        result = await provider.crawl(candidate, budget=budget)

        assert result["crawler_status"] == "STAGE_A_CONFIRMED"
        # Only 1 scrape executed despite budget allowing 4
        assert mock_scrape.call_count == 1


# 6. Firecrawl Failure Resilience (Directive 68)
@pytest.mark.asyncio
async def test_firecrawl_failure_retains_candidate_needs_research(clean_cache):
    """Directive 68: If Firecrawl fails, retain Exa candidate with status NEEDS_RESEARCH."""
    provider = FirecrawlCrawlerProvider(api_key="test-key", enabled=True, dry_run=False)
    url = "https://failing-site.com/press"

    failed_doc = CrawledDocument(
        url=url,
        canonical_url=canonical_url(url),
        title="",
        content="",
        content_hash=hashlib.sha256(b"").hexdigest(),
        provider="firecrawl",
        status="FAILED",
        metadata={"error": "503 Service Unavailable"},
    )

    with patch.object(provider, "_scrape_safe", AsyncMock(return_value=failed_doc)):
        candidate = {
            "title": "FailingSite hires Privacy Counsel",
            "snippet": "FailingSite establishes India compliance presence",
            "source_url": url,
            "company": {"name": "FailingSite", "country": "India"},
        }
        budget = ProviderBudget()
        result = await provider.crawl(candidate, budget=budget)

        assert result["crawler_status"] == "NEEDS_RESEARCH"
        assert result["company"]["name"] == "FailingSite"


# 7. Dry-Run Mode Safety (Directive 35)
@pytest.mark.asyncio
async def test_dry_run_mode_does_not_call_firecrawl(clean_cache):
    """Directive 35: In dry run mode, candidate tagged WOULD_CRAWL and Firecrawl is never called."""
    provider = FirecrawlCrawlerProvider(api_key="test-key", enabled=True, dry_run=True)
    with patch.object(provider, "_scrape_safe", AsyncMock()) as mock_scrape:
        candidate = {
            "title": "Apex appoints DPO",
            "snippet": "Apex DPDP compliance expansion",
            "source_url": "https://apex.com/news",
            "company": {"name": "Apex", "country": "India"},
        }
        result = await provider.crawl(candidate)
        assert result["crawler_status"] == "WOULD_CRAWL"
        assert mock_scrape.call_count == 0


# 8. LiveDiscoveryService Orchestration (Directive 59, 67)
@pytest.mark.asyncio
async def test_live_discovery_service_dry_run(db, clean_cache):
    service = LiveDiscoveryService(db)
    estimate = service.estimate(max_queries=2, dry_run=True)
    assert estimate.dry_run is True
    assert estimate.worst_case_firecrawl_calls == 0

    mock_candidates = [
        {
            "id": "doc-test-1",
            "title": "Alpha Corp appoints Data Protection Officer for DPDP compliance",
            "snippet": "Alpha Corp announces new DPO in India.",
            "source_url": "https://alphacorp.com/news/dpo",
            "source_name": "Alpha News",
            "source_type": "press_release",
            "published_date": "2026-10-05T00:00:00Z",
            "retrieved_at": "2026-10-07T00:00:00Z",
            "content_hash": "hash_alpha_1",
            "company": {"name": "Alpha Corp", "sector": "SaaS", "country": "India"},
            "confidence": 0.85,
        }
    ]

    with patch(
        "leados.services.live_discovery.ExaSearchProvider.search", AsyncMock(return_value=mock_candidates)
    ):
        summary = await service.run(max_queries=1, dry_run=True)
        assert summary.dry_run is True
        assert summary.candidates_screened == 1
        assert summary.candidates_passed_prescreen == 1
        assert summary.status == "COMPLETED"


# 9. API Endpoints (Directives 53, 54, 55, 56)
def test_provider_status_and_health_endpoints(client):
    res_status = client.get("/providers/status")
    assert res_status.status_code == 200
    data = res_status.json()
    assert "search" in data
    assert "crawler" in data
    from leados.config import settings

    assert data["mode"] == settings.live_research_mode
    assert data["email_enabled"] is False

    res_exa = client.get("/providers/exa/health")
    assert res_exa.status_code == 200
    assert res_exa.json()["provider"] == "exa"

    res_fc = client.get("/providers/firecrawl/health")
    assert res_fc.status_code == 200
    assert res_fc.json()["provider"] == "firecrawl"


def test_pipeline_discover_live_estimate_endpoint(client):
    res = client.post("/pipeline/discover/live/estimate", json={"max_queries": 2})
    assert res.status_code == 200
    data = res.json()
    assert data["queries_to_run"] <= 2
    assert "worst_case_exa_calls" in data
    assert "worst_case_firecrawl_calls" in data


@pytest.mark.asyncio
async def test_live_discovery_promotes_to_main_dashboard_with_thesis_and_draft(db, clean_cache, client):
    """Verify live discovery creates BD opportunities on the main dashboard with commercial thesis,

    OpenAI outreach draft, and Google Sheets Master View projection, without disrupting live crawler invariants.
    """
    from leados.services.master_view import MasterViewService
    from leados.storage.records import Opportunity, OutreachDraft

    service = LiveDiscoveryService(db)
    mock_candidate = {
        "id": "doc-live-opp-1",
        "title": "Tata Digital invites proposals for external consulting to support DPDP compliance programme",
        "snippet": "Tata Digital invites proposals for external consulting to operationalize India DPDP Act compliance and privacy framework across consumer platforms.",
        "source_url": "https://tatadigital.com/procurement/dpdp-rfp",
        "source_name": "Tata Digital Procurement",
        "source_type": "procurement_notice",
        "published_date": "2026-10-06",
        "retrieved_at": "2026-10-07T00:00:00Z",
        "content_hash": "hash_tata_digital_1",
        "company": {
            "name": "Tata Digital",
            "domain": "tatadigital.com",
            "sector": "E-Commerce",
            "country": "India",
            "employee_range": "1000-5000",
            "funding_stage": "Enterprise",
            "locations": ["India"],
            "description": "Tata Digital consumer platform",
        },
        "confidence": 0.90,
    }

    with (
        patch(
            "leados.services.live_discovery.ExaSearchProvider.search",
            AsyncMock(return_value=[mock_candidate]),
        ),
        patch(
            "leados.services.live_discovery.FirecrawlCrawlerProvider.enrich_candidate",
            AsyncMock(
                return_value={
                    **mock_candidate,
                    "firecrawl_decision": "CALL_EXECUTED",
                    "crawler_status": "SUCCESS",
                }
            ),
        ),
    ):
        summary = await service.run(max_queries=1, dry_run=False)
        assert summary.status == "COMPLETED"
        assert summary.opportunities_created == 1
        assert len(summary.results) == 1
        assert summary.results[0]["status"] == "VERIFIED_OPPORTUNITY"
        opp_id = summary.results[0]["opportunity_ids"][0]

        opp = db.get(Opportunity, opp_id)
        assert opp is not None
        assert opp.human_status == "PENDING_REVIEW"
        assert opp.commercial_thesis is not None
        assert len(opp.commercial_thesis) > 0

        # OutreachDraft generated
        draft = db.first(OutreachDraft, opportunity_id=opp.id)
        assert draft is not None
        assert len(draft.subjects) > 0
        assert len(draft.body) > 0

        # Master View projection for Google Sheets contains the opportunity
        rows = MasterViewService(db).build_rows()
        opp_row = next((r for r in rows if r.get("opportunity_id") == opp.id), None)
        assert opp_row is not None
        assert opp_row["review_status"] == "PENDING REVIEW"
        assert opp_row["company"] == "Tata Digital"
        assert opp_row["record_type"] == "QUALIFIED_OPPORTUNITY"

        # Test review endpoint allows human approval
        res_review = client.post(
            f"/opportunities/{opp.id}/approve",
            json={"reviewer": "adesh", "notes": "Approved for outreach"},
        )
        assert res_review.status_code == 200
        assert res_review.json()["human_status"] == "APPROVED"

