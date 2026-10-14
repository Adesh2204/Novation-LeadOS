"""Production gates use realistic public-source fixtures; no actual provider spending."""

import copy
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from leados.config import settings
from leados.engine import digest
from leados.pipeline import Pipeline
from leados.providers.cache import ProviderCache
from leados.providers.future.exa import ExaSearchProvider
from leados.providers.future.firecrawl import FirecrawlCrawlerProvider
from leados.providers.models import ProviderBudget
from leados.qualification import SCORE_VERSION, qualify
from leados.services.discovery_results import discovery_rows
from leados.services.live_discovery import LiveDiscoveryService
from leados.services.master_view import MasterViewService
from leados.services.provenance import apply_classification, classify, qualified_opportunity
from leados.storage.records import (
    Company,
    CompanySignal,
    HumanReview,
    Opportunity,
    OpportunityEvidence,
    ProviderRun,
    ScoreComponent,
    SourceDocument,
)


async def test_origin_archive_retains_graph_and_default_live_view_is_empty(db):
    with db.transaction():
        await Pipeline(db, as_of=date(2026, 10, 6)).run()
        before = {
            model.__name__: len(db.list(model))
            for model in (Company, Opportunity, SourceDocument, HumanReview)
        }
        report = classify(db)
        assert report["dependencies_valid"] and report["deletion_count"] == 0
        assert report["counts"]["Company"] == {"MOCK": 40}
        assert report["counts"]["Opportunity"] == {"MOCK": 44}
        apply_classification(db, report)
        assert all(o.archived_at and o.record_origin == "MOCK" for o in db.list(Opportunity))
        assert MasterViewService(db).build_rows() == []
        assert len(MasterViewService(db).build_rows("MOCK")) == 44
        assert not any(qualified_opportunity(o) for o in db.list(Opportunity))
        assert {
            model.__name__: len(db.list(model))
            for model in (Company, Opportunity, SourceDocument, HumanReview)
        } == before


def real_document(text, name="Acme Systems", path="requirement"):
    return {
        "company": {
            "name": name,
            "aliases": [],
            "domain": "acme.com",
            "country": "India",
            "sector": "SaaS",
            "employee_range": "Unknown",
            "funding_stage": "Unknown",
            "locations": ["India"],
            "description": "Enterprise",
        },
        "source_url": "https://acme.com/" + path,
        "source_name": "Acme procurement",
        "source_type": "procurement_notice",
        "published_date": date.today().isoformat(),
        "snippet": text,
        "confidence": 0.85,
        "company_match": True,
        "assertion_type": "FACT",
        "conflict": False,
        "record_origin": "LIVE",
        "provenance": {"provider": "exa", "source_url": "https://acme.com/" + path},
    }


@pytest.mark.parametrize(
    "text,status,role",
    [
        (
            "Acme Systems launches a DPDP governance platform for customers.",
            "NOT_A_BUYER",
            "SOLUTION_PROVIDER",
        ),
        (
            "Acme Systems is hiring a data protection officer to lead privacy governance.",
            "NEEDS_RESEARCH",
            "POTENTIAL_BUYER",
        ),
        (
            "Acme Systems publishes an AI governance blog about responsible AI.",
            "TOPIC_MATCH_ONLY",
            "NEWS_ONLY",
        ),
        ("Acme Systems announces an acquisition of a software company.", "NEEDS_RESEARCH", "POTENTIAL_BUYER"),
        ("Acme Systems offers a contract lifecycle software platform.", "NOT_A_BUYER", "SOLUTION_PROVIDER"),
        ("Acme Systems launches a vendor risk software product.", "NOT_A_BUYER", "SOLUTION_PROVIDER"),
        ("Acme Systems is hiring an internal legal operations manager.", "NEEDS_RESEARCH", "POTENTIAL_BUYER"),
        (
            "Acme Systems denies an allegation of misconduct. No external investigation support requested.",
            "TOPIC_MATCH_ONLY",
            "NEWS_ONLY",
        ),
    ],
)
def test_false_positive_commercial_outcomes(text, status, role):
    q = qualify(real_document(text))
    assert q["status"] == status and q["organization_role"] == role
    assert q["method"] == "RULE_BASED" and not q["service_demand"]


SCOPES = [
    ("privacy", "DPDP privacy assessment"),
    ("clm", "contract review backlog remediation"),
    ("ai_governance", "AI governance risk assessment"),
    ("corporate_compliance", "corporate compliance entity coordination"),
    ("legal_operations", "legal operations workflow support"),
    ("vendor_governance", "third party risk assessment"),
    ("investigations_disputes", "forensic investigation support"),
    ("transaction_integration", "due diligence"),
    ("technology_ip", "software licensing advice"),
]


@pytest.mark.parametrize("vertical,scope", SCOPES)
async def test_each_vertical_requires_own_demand_and_reproducible_score(db, vertical, scope):
    doc = real_document(
        f"Acme Systems is seeking external consulting support for {scope}. The engagement concerns its own enterprise operations."
    )
    q = qualify(doc)
    assert q["status"] == "QUALIFIED_SIGNAL" and q["vertical_ids"] == [vertical]
    with db.transaction():
        run = await Pipeline(db).run_documents([doc], live=True)
        assert run.status == "COMPLETED", run.error
        assert run.metrics["opportunities_created"] == 1
    op = db.list(Opportunity)[0]
    assert op.vertical_id == vertical and op.record_origin == "LIVE"
    assert op.score_version == SCORE_VERSION and op.audit_status == "VERIFIED"
    parts = db.list(ScoreComponent, opportunity_id=op.id)
    assert sum(p.points for p in parts) == op.score <= 100
    assert len(parts) == 8 and op.score_inputs["qualification_version"]
    assert next(p for p in parts if p.name == "identifiable_need").points < 25
    assert len(MasterViewService(db).build_rows()) == 1
    with db.transaction():
        repeat = await Pipeline(db).run_documents([copy.deepcopy(doc)], live=True)
    assert repeat.metrics["opportunities_created"] == 0
    assert db.get(Opportunity, op.id).score == op.score


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("published_date", None, "timing"),
        ("published_date", "2099-01-01", "timing"),
        ("published_date", "2020-01-01", "timing"),
        ("confidence", 0.3, "reliability"),
        ("assertion_type", "ALLEGATION", "allegation"),
        ("company_match", False, "identity"),
        ("conflict", True, "conflicting"),
    ],
)
def test_service_requirement_still_needs_evidence_gates(field, value, reason):
    doc = real_document("Acme Systems is seeking external consulting support for privacy assessment.")
    doc[field] = value
    q = qualify(doc)
    assert q["status"] == "NEEDS_RESEARCH" and reason in q["reason"].lower()


def test_rfp_timing_and_eligibility_are_not_invented():
    text = "Acme Systems issues a request for proposal for independent DPDP privacy assessment."
    q = qualify(real_document(text))
    assert q["status"] == "NEEDS_RESEARCH" and "closing date" in q["reason"] and "eligibility" in q["reason"]
    q = qualify(real_document(text + " Qualified consulting firms are eligible. Closing date: 2099-01-01."))
    assert q["status"] == "QUALIFIED_SIGNAL"
    q = qualify(real_document(text + " Qualified consulting firms are eligible. Closing date: 2020-01-01."))
    assert q["status"] == "NEEDS_RESEARCH" and "passed" in q["reason"]


async def test_multi_source_event_consolidates_one_opportunity_and_preserves_reviews(db):
    doc = real_document("Acme Systems is seeking external consulting support for privacy assessment.")
    second = real_document(doc["snippet"] + " Scope includes data flow mapping.", path="notice-2")
    with db.transaction():
        await Pipeline(db).run_documents([doc], live=True)
        op = db.list(Opportunity)[0]
        db.add(HumanReview(opportunity_id=op.id, reviewer="Reviewer", decision="APPROVED", notes="Keep"))
    old_score = op.score
    with db.transaction():
        run = await Pipeline(db).run_documents([second], live=True)
    assert run.metrics["opportunities_created"] == 0
    assert run.metrics["dedup"]["updated_history"] == 1
    assert len(db.list(Opportunity)) == 1
    assert len(db.list(OpportunityEvidence, opportunity_id=op.id)) == 2
    assert len(db.get(CompanySignal, op.company_signal_id).evidence_ids) == 2
    assert len(db.list(HumanReview)) == 1 and db.get(Opportunity, op.id).score == old_score


async def test_internal_hiring_stores_research_without_opportunity(db):
    doc = real_document("Acme Systems is hiring a data protection officer to lead privacy governance.")
    with db.transaction():
        run = await Pipeline(db).run_documents([doc], live=True)
    assert run.status == "COMPLETED"
    assert len(db.list(Company)) == len(db.list(SourceDocument)) == 1
    assert len(db.list(CompanySignal)) == 1 and db.list(Opportunity) == []


@pytest.fixture
def isolated_providers(monkeypatch, tmp_path):
    cache = ProviderCache(tmp_path / "provider-cache.json")
    for module in [
        "leados.providers.future.exa",
        "leados.providers.future.firecrawl",
        "leados.services.live_discovery",
    ]:
        monkeypatch.setattr(module + ".provider_cache", cache)
    monkeypatch.setattr(settings, "discovery_jobs_path", str(tmp_path / "jobs"))
    monkeypatch.setattr(settings, "live_research_mode", "EXA_FIRECRAWL")
    return cache


async def test_sdk_normalization_cached_summary_and_repeat_dataset(db, isolated_providers, monkeypatch):
    doc = real_document(
        "Acme Systems is seeking external consulting support for DPDP privacy assessment. "
        + "The independent scope concerns enterprise data governance. " * 4
    )
    client = MagicMock()
    client.search.return_value = SimpleNamespace(
        results=[
            SimpleNamespace(
                url=doc["source_url"],
                title="Acme Systems privacy requirement",
                highlights=[doc["snippet"]],
                published_date=doc["published_date"],
                author=None,
                score=0.99,
            )
        ],
        output=SimpleNamespace(
            content={
                "events": [
                    {
                        "company_name": "Acme Systems",
                        "country": "India",
                        "sector": "SaaS",
                        "source_url": doc["source_url"],
                        "event_summary": "External privacy assessment required",
                    }
                ]
            }
        ),
    )
    monkeypatch.setattr(ExaSearchProvider, "_get_client", lambda self: client)
    with db.transaction():
        first = await LiveDiscoveryService(db).run(max_queries=1, max_companies=2, dry_run=False)
    assert first.exa_queries == 1 and first.firecrawl_requests == 0
    assert first.results[0]["firecrawl_decision"] == "SOURCE_ALREADY_SUFFICIENT"
    assert first.opportunities_created == 1 and first.results[0]["status"] == "VERIFIED_OPPORTUNITY"
    with db.transaction():
        repeat = await LiveDiscoveryService(db).run(max_queries=1, max_companies=2, dry_run=False)
    assert repeat.exa_queries == repeat.firecrawl_requests == 0 and repeat.exa_cache_hits == 1
    assert repeat.opportunities_created == 0 and repeat.results[0]["status"] == "EXISTING_OPPORTUNITY"
    assert len(db.list(Opportunity)) == 1 and client.search.call_count == 1
    assert all(row["record_origin"] == "LIVE" for row in discovery_rows(db))


async def test_firecrawl_sdk_page_reaches_pipeline_and_counts_requests(db, isolated_providers, monkeypatch):
    short = real_document("Acme Systems requests privacy assessment. DPDP procurement.")
    group = LiveDiscoveryService(db)._select_queries(max_queries=1)[0]
    isolated_providers.set_search(group["query"], [short])
    content = (
        "Acme Systems is seeking external consulting support for privacy assessment and data flow mapping."
    )
    app = MagicMock()
    app.scrape.return_value = {
        "markdown": content,
        "metadata": {"title": "Acme privacy requirement", "published_date": date.today().isoformat()},
    }
    monkeypatch.setattr(FirecrawlCrawlerProvider, "_get_app", lambda self: app)
    with db.transaction():
        summary = await LiveDiscoveryService(db).run(max_queries=1, max_companies=2, dry_run=False)
    assert summary.status == "COMPLETED", summary.error
    assert summary.exa_queries == 0 and summary.firecrawl_requests == summary.firecrawl_pages == 1
    assert summary.firecrawl_verified_pages == 1
    source = db.list(SourceDocument)[0]
    assert source.snippet == content and source.provenance["exa_excerpt"] == short["snippet"]
    assert source.provenance["firecrawl"]["content_hash"] == digest(content)
    assert db.list(Opportunity)[0].audit_status == "VERIFIED"


async def test_firecrawl_cache_no_budget_and_cooperative_stop(isolated_providers):
    doc = real_document("Acme Systems privacy officer vacancy and DPDP governance.")
    cached = {
        "url": doc["source_url"],
        "canonical_url": doc["source_url"],
        "title": "Acme privacy",
        "content": doc["snippet"],
        "content_hash": digest(doc["snippet"]),
        "status": "SUCCESS",
    }
    isolated_providers.set_crawl(doc["source_url"], cached)
    crawler = FirecrawlCrawlerProvider(enabled=True, dry_run=False)
    result = await crawler.enrich_candidate(doc, ProviderBudget(max_firecrawl_pages=0))
    assert result["firecrawl_decision"] == "CACHE_REUSED" and crawler.actual_requests == 0


def test_query_rotation_covers_all_114_signals_once():
    service = LiveDiscoveryService()
    groups = service.query_catalog
    ids = [sid for group in groups for sid in group["signal_ids"]]
    assert len(ids) == len(set(ids)) == 114 and len(groups) == 9
    assert service._select_queries(max_queries=1, query_offset=0) != service._select_queries(
        max_queries=1, query_offset=1
    )
    assert set(v for group in groups for v in group["vertical_ids"]) == set(v for v, _ in SCOPES)


async def test_stop_retains_partial_results_without_new_calls(db, isolated_providers):
    with db.transaction():
        summary = await LiveDiscoveryService(db).run(max_queries=2, dry_run=False, should_stop=lambda: True)
    assert summary.status == "PARTIAL" and summary.error == "discovery_stopped"
    assert summary.exa_queries == summary.firecrawl_requests == 0
    assert len(db.list(ProviderRun)) == 1


def test_sdk_search_http_timeout_is_bounded(monkeypatch):
    import httpx

    from leados.providers.future.exa import TimedExa

    calls = []

    def request(method, url, **kwargs):
        calls.append(kwargs)
        return httpx.Response(200, json={"results": []}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", request)
    response = TimedExa(api_key="test-key").request("/search", {"query": "privacy assessment"})
    assert response == {"results": []} and len(calls) == 1
    assert calls[0]["timeout"] == settings.exa_timeout_seconds


async def test_additional_target_page_keeps_its_own_provenance(isolated_providers, monkeypatch):
    crawler = FirecrawlCrawlerProvider(enabled=True, dry_run=False)
    doc = real_document("Acme Systems DPDP privacy assessment procurement notice.")
    target = "https://acme.com/tender-document"
    doc["additional_target_urls"] = [target]
    app = MagicMock()
    app.scrape.side_effect = [
        {"markdown": "Acme Systems privacy procurement announcement.", "metadata": {"title": "Announcement"}},
        {
            "markdown": "Acme Systems is seeking external privacy assessment consulting support.",
            "metadata": {"title": "Scope"},
        },
    ]
    monkeypatch.setattr(crawler, "_get_app", lambda: app)
    result = await crawler.enrich_candidate(
        doc, ProviderBudget(max_firecrawl_pages=2, max_pages_per_company=2)
    )
    assert crawler.actual_requests == 2 and len(result["additional_documents"]) == 1
    extra = result["additional_documents"][0]
    assert extra["source_url"] == target and extra["provenance"]["firecrawl"]["url"] == target
    assert result["provenance"]["firecrawl"]["url"] == doc["source_url"]
    assert result["snippet"] != extra["snippet"]


async def test_partial_provider_error_retains_research(db, isolated_providers, monkeypatch):
    from leados.providers.base import ProviderError

    doc = real_document("Acme Systems privacy assessment DPDP procurement.")
    isolated_providers.set_search(LiveDiscoveryService(db)._select_queries(max_queries=1)[0]["query"], [doc])

    def unavailable(self):
        raise ProviderError("missing_firecrawl_api_key", retryable=False)

    monkeypatch.setattr(FirecrawlCrawlerProvider, "_get_app", unavailable)
    with db.transaction():
        summary = await LiveDiscoveryService(db).run(max_queries=1, dry_run=False)
    assert summary.status == "PARTIAL" and summary.firecrawl_requests == 0
    assert summary.results[0]["firecrawl_decision"] == "PROVIDER_ERROR"
    assert len(discovery_rows(db)) == 1 and db.list(Opportunity) == []


async def test_live_and_development_dashboard_views_are_separate(client, populated):
    default = client.get("/dashboard/state").json()
    assert default["metrics"]["companies"] == default["metrics"]["opportunities"] == 0
    assert default["opportunities"] == [] and client.get("/opportunities").json() == []
    development = client.get("/dashboard/state?data_mode=MOCK").json()
    assert development["data_mode"] == "MOCK" and len(development["opportunities"]) == 44
    assert development["metrics"]["companies"] == 40


async def test_distinct_rfp_references_are_distinct_events(db):
    docs = [
        real_document(
            f"Acme Systems issues RFP number PRIV-{n} for external privacy assessment. Qualified consulting firms are eligible. Closing date: 2099-01-01.",
            path=f"rfp-{n}",
        )
        for n in (1, 2)
    ]
    with db.transaction():
        run = await Pipeline(db).run_documents(docs, live=True)
    assert run.metrics["opportunities_created"] == 2
    assert len({s.event_key for s in db.list(CompanySignal)}) == 2


async def test_historical_score_is_versioned_when_new_buyer_evidence_qualifies(db):
    old = real_document("Acme Systems starts a privacy control implementation programme.")
    with db.transaction():
        await Pipeline(db).run_documents([old])
        op = db.list(Opportunity)[0]
        historical_score = op.score
        for model in (Company, SourceDocument, CompanySignal, Opportunity):
            for record in db.list(model):
                record.record_origin = "LIVE"
        db.add(
            HumanReview(
                opportunity_id=op.id,
                reviewer="Historical reviewer",
                decision="MONITOR",
                notes="Keep original review",
            )
        )
    new = real_document(
        "Acme Systems is seeking external consulting support for privacy assessment.", path="new-buyer-source"
    )
    with db.transaction():
        run = await Pipeline(db).run_documents([new], live=True)
    assert run.metrics["opportunities_created"] == 0
    updated = db.get(Opportunity, op.id)
    assert updated.score_version == SCORE_VERSION
    assert updated.evaluation_history[0]["score"] == historical_score
    assert updated.evaluation_history[0]["score_version"] == "1.0.0"
    assert updated.audit_status == "VERIFIED" and len(db.list(HumanReview)) == 1
    assert len(db.list(OpportunityEvidence, opportunity_id=op.id)) == 2


def test_adjacent_sector_and_vendor_rfp_marketing_need_review():
    doc = real_document("Acme Systems is seeking external privacy assessment consulting support.")
    doc["company"]["sector"] = "Unverified adjacent sector"
    assert qualify(doc)["status"] == "NEEDS_RESEARCH"
    marketing = real_document(
        "Acme Systems offers an RFP automation privacy platform. Qualified consulting firms are eligible. Closing date: 2099-01-01."
    )
    assert qualify(marketing)["status"] == "NOT_A_BUYER"


def test_http_200_security_page_is_not_successful_evidence(isolated_providers):
    app = MagicMock()
    app.scrape.return_value = {
        "markdown": "GeM Information Security: The page is blocked due to Security Issue.",
        "metadata": {"statusCode": 200},
    }
    crawler = FirecrawlCrawlerProvider(api_key="test", enabled=True, dry_run=False)
    page = crawler._sync_scrape(app, "https://gem.gov.in/requirement")
    assert page.status == "FAILED"
    assert page.metadata["error"] == "robots_or_access_restricted"
    assert crawler.actual_requests == 1


async def test_cached_security_page_preserves_exa_and_never_calls_sdk(isolated_providers, monkeypatch):
    doc = real_document("Acme Systems is seeking external DPDP privacy assessment.")
    blocked = {"content": "The page is blocked due to Security Issue.", "status": "SUCCESS"}
    isolated_providers.set_crawl(doc["source_url"], blocked)
    crawler = FirecrawlCrawlerProvider(api_key="test", enabled=True, dry_run=False)
    monkeypatch.setattr(crawler, "_get_app", lambda: pytest.fail("Cached restriction must not retry"))
    result = await crawler.enrich_candidate(doc)
    assert result["snippet"] == doc["snippet"]
    assert result["firecrawl_decision"] == "ROBOTS_OR_ACCESS_RESTRICTED"
    assert result["crawl_cache_reused"] and crawler.actual_requests == 0
    assert result["provenance"]["source_error"] == "robots_or_access_restricted"
    assert qualify(result)["status"] == "NEEDS_RESEARCH"


async def test_blocked_stored_body_is_repaired_without_losing_history(db):
    doc = real_document("The page is blocked due to Security Issue.")
    with db.transaction():
        await Pipeline(db).run_documents([doc], live=True)
    stored = db.list(SourceDocument)[0]
    old_hash = stored.content_hash
    recovered = real_document("Acme Systems is seeking external DPDP privacy assessment.")
    recovered["provenance"]["source_error"] = "robots_or_access_restricted"
    with db.transaction():
        await Pipeline(db).run_documents([recovered], live=True)
    stored = db.get(SourceDocument, stored.id)
    assert stored.snippet == recovered["snippet"]
    assert stored.content_history[0]["content_hash"] == old_hash
    assert not db.list(Opportunity)


def test_procurement_bidder_boilerplate_does_not_classify_issuer_as_seller():
    doc = real_document(
        "Acme Systems invites e-tenders from service providers for procurement of a litigation management solution. "
        "Offers received from bidders must comply with this Request for Proposal."
    )
    q = qualify(doc)
    assert q["status"] == "NEEDS_RESEARCH" and q["organization_role"] != "SOLUTION_PROVIDER"
    assert not q["service_demand"]


def test_explicit_company_name_matches_with_trailing_acronym_and_markup():
    from leados.qualification import company_name_supported

    company = {"name": "Life Insurance Corporation of India (LIC)", "aliases": []}
    assert company_name_supported(company, "**Life Insurance Corporation of India** Central Office")
    assert not company_name_supported(company, "An unrelated insurer is issuing a request.")
