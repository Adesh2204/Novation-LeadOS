import asyncio
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from leados.api import app
from leados.config import Settings, settings
from leados.engine import detect_signals
from leados.knowledge import knowledge
from leados.pipeline import Pipeline
from leados.providers.base import ProviderError, ProviderExecutor, ProviderPolicy
from leados.providers.cache import ProviderCache
from leados.providers.factory import get_providers
from leados.providers.future.contacts import ContactOutContactProvider, SnovioContactProvider
from leados.providers.future.exa import ExaSearchProvider
from leados.providers.future.hubspot import HubSpotCRMProvider
from leados.providers.future.openai import OpenAIEmbeddingProvider, OpenAILLMProvider
from leados.providers.http import VendorHTTP
from leados.schemas import ResearchOutput
from leados.services.live_discovery import LiveDiscoveryService
from leados.storage.factory import api_write_lock, get_db
from leados.storage.records import AuditLog, Company, Opportunity


def document():
    return {
        "company": {
            "name": "Acme Systems",
            "aliases": [],
            "domain": "acme.com",
            "country": "India",
            "sector": "SaaS",
            "employee_range": "501-1000",
            "funding_stage": "Series B",
            "locations": ["India"],
            "description": "Enterprise software",
        },
        "source_url": "https://acme.com/news/ai-recruitment",
        "source_name": "Acme announcement",
        "source_type": "company_website",
        "published_date": date.today().isoformat(),
        "snippet": "Acme Systems launches an AI recruitment decision system and appoints an AI governance lead.",
        "confidence": 0.95,
        "assertion_type": "FACT",
        "company_match": True,
        "conflict": False,
        "jurisdiction": "India",
        "language": "en",
    }


def test_new_config_keys_and_mock_isolation(monkeypatch):
    config = Settings(
        _env_file=None,
        CONTACT_OUT_API_KEY="contact-key",
        OPENAI_API_KEY="ai-key",
        SNOVIO_USER_ID="client",
        SNOVIO_SECRET="secret",
        HUBSPOT_ACCESS_TOKEN="crm-key",
        N8N_ENCRYPTION_KEY="local-key",
        N8N_SECURE_COOKIE=False,
    )
    assert config.contact_out_api_key == "contact-key"
    assert config.openai_api_key == "ai-key"
    assert config.snovio_user_id == "client" and config.snovio_secret == "secret"
    assert config.hubspot_access_token == "crm-key"
    assert not config.n8n_secure_cookie
    for field, value in {
        "llm_provider": "openai",
        "embedding_provider": "openai",
        "contact_provider": "contactout_snovio",
        "crm_provider": "hubspot",
    }.items():
        monkeypatch.setattr(settings, field, value)
    providers = get_providers()
    assert all(
        getattr(providers, name).name.startswith("mock")
        for name in ["search", "crawler", "llm", "embeddings", "contacts", "crm", "email"]
    )
    assert get_providers(live=True).contacts.name == "contactout"


def test_live_catalog_covers_all_verticals_and_only_real_signals(db):
    service = LiveDiscoveryService(db)
    for vertical in knowledge.verticals:
        assert service._select_queries([vertical], max_queries=10), vertical
    assert all(
        set(group.get("signal_ids", [])).issubset(knowledge.signals) for group in service.query_catalog
    )


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Acme is looking for an experienced Data Protection Officer", True),
        ("Acme is hiring a DPO to lead privacy governance", True),
        ("Acme is not hiring a DPO", False),
        ("Article explains the responsibilities of a Data Protection Officer", False),
    ],
)
def test_live_hiring_detection_requires_a_concrete_event(text, expected):
    assert ("DPO_HIRING" in detect_signals(text, knowledge.signals, live=True)) is expected


async def test_natural_hiring_language_reaches_scoring_and_verification(db):
    row = document()
    row["snippet"] = (
        "Acme Systems is looking for an experienced Data Protection Officer to lead enterprise-wide privacy governance in India."
    )
    with db.transaction():
        run = await Pipeline(db).run_documents([row], live=True)
    assert run.status == "COMPLETED"
    assert db.list(Opportunity) == []
    assert run.state["source_qualifications"]
    assert all(q["status"] == "NEEDS_RESEARCH" for q in run.state["source_qualifications"].values())


@pytest.mark.parametrize(
    "status,code",
    [(401, "invalid_credentials"), (403, "access_denied"), (402, "credits_required"), (429, "rate_limited")],
)
async def test_permanent_vendor_errors_are_safe_and_not_retried(status, code):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={"error": "secret-key-must-not-appear"})

    vendor = VendorHTTP("vendor", "https://vendor.test", {"token": "secret"}, httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match=f"vendor_{code}") as error:
        await ProviderExecutor(ProviderPolicy()).call(lambda: vendor.request("GET", "/stats"))
    assert len(requests) == 1
    assert "secret" not in str(error.value)


async def test_contactout_current_work_email_payload(monkeypatch):
    monkeypatch.setattr(settings, "contact_out_api_key", "token-value")

    def handler(request):
        body = json.loads(request.content)
        assert request.headers["token"] == "token-value"
        assert request.headers["authorization"] == "basic"
        assert body["page_size"] == 3 and body["data_types"] == ["work_email"]
        assert body["domain"] == ["acme.com"] and body["match_experience"] == "current"
        return httpx.Response(
            200,
            json={
                "profiles": {
                    "linkedin": {
                        "full_name": "Test Counsel",
                        "experience": [
                            {"is_current": True, "domain": "acme.com", "title": "General Counsel"}
                        ],
                        "contact_info": {
                            "work_emails": ["counsel@acme.com"],
                            "personal_emails": ["private@example.com"],
                        },
                    }
                }
            },
        )

    contacts = await ContactOutContactProvider(httpx.MockTransport(handler)).enrich(
        {"domain": "acme.com"}, ["General Counsel"]
    )
    assert contacts[0]["contact_email"] == "counsel@acme.com"
    assert contacts[0]["contact_status"] == "FOUND_UNVERIFIED"
    assert "private" not in json.dumps(contacts)


async def test_snov_auth_is_cached_and_catchall_never_validated(monkeypatch):
    monkeypatch.setattr(settings, "snovio_user_id", "client-id")
    monkeypatch.setattr(settings, "snovio_secret", "client-secret")
    requests = []

    def handler(request):
        requests.append(request)
        assert "client-secret" not in str(request.url)
        if request.url.path.endswith("access_token"):
            assert b"grant_type=client_credentials" in request.content
            return httpx.Response(200, json={"access_token": "access", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer access"
        if request.url.path.endswith("start"):
            return httpx.Response(200, json={"data": {"task_hash": "valid-task"}})
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "data": [
                    {"email": "valid@acme.com", "result": {"smtp_status": "valid", "is_valid_format": True}},
                    {
                        "email": "catchall@acme.com",
                        "result": {
                            "smtp_status": "unknown",
                            "is_valid_format": True,
                            "unknown_status_reason": "catchall",
                        },
                    },
                ],
            },
        )

    provider = SnovioContactProvider(httpx.MockTransport(handler))
    result = await provider.verify(["valid@acme.com", "catchall@acme.com"])
    await provider.authorize()
    assert result == {"valid@acme.com": "VALIDATED", "catchall@acme.com": "UNVERIFIED"}
    assert sum(request.url.path.endswith("access_token") for request in requests) == 1
    assert all("campaign" not in str(request.url) for request in requests)


async def test_openai_rejects_unknown_citations():
    output = ResearchOutput(
        inferences=[{"type": "INFERENCE", "text": "Hypothesis", "evidence_ids": ["invented-id"]}],
        commercial_thesis="Assess",
        why_now="Event",
        outreach_angle="Discuss",
        need=0.5,
        mandate_value=0.5,
    )
    client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=AsyncMock(return_value=SimpleNamespace(status="completed", output_parsed=output))
        )
    )
    with pytest.raises(ProviderError, match="openai_invalid_evidence_reference"):
        await OpenAILLMProvider(client).research({"evidence_ids": ["actual-id"], "evidence": [document()]})
    assert client.responses.parse.call_args.kwargs["store"] is False


async def test_embedding_cache_and_order():
    client = SimpleNamespace(
        embeddings=SimpleNamespace(
            create=AsyncMock(
                return_value=SimpleNamespace(
                    data=[
                        SimpleNamespace(index=1, embedding=[0.0, 1.0]),
                        SimpleNamespace(index=0, embedding=[1.0, 0.0]),
                    ]
                )
            )
        )
    )
    provider = OpenAIEmbeddingProvider(client)
    first = await provider.embed(["a", "b", "a"])
    assert first == [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]]
    assert await provider.embed(["b"]) == [[0.0, 1.0]]
    assert client.embeddings.create.call_count == 1


async def test_live_entry_runs_all_stages_and_retries_deduplicate(db, tmp_path, monkeypatch):
    cache = ProviderCache(tmp_path / "providers.json")
    monkeypatch.setattr("leados.services.live_discovery.provider_cache", cache)
    search = AsyncMock(return_value=[document()])

    async def crawl(self, candidate, budget):
        budget.record_firecrawl_page("acme.com")
        return {**candidate, "crawler_status": "STAGE_A_CONFIRMED", "crawled_content_hash": "hash"}

    with (
        patch("leados.services.live_discovery.ExaSearchProvider.search", search),
        patch("leados.services.live_discovery.FirecrawlCrawlerProvider.enrich_candidate", crawl),
        patch("leados.services.live_discovery.get_providers", return_value=get_providers()),
    ):
        service = LiveDiscoveryService(db)
        with db.transaction():
            result = await service.run(max_queries=1, dry_run=False)
        assert result.status == "COMPLETED" and result.opportunities_created == 0
        assert result.firecrawl_requests == 0  # SDK mocked at the enrichment layer; no actual request.
        assert result.pipeline_run_id
        assert search.call_args.kwargs["query"] == service._select_queries(max_queries=1)[0]["query"]
        assert {row.module for row in db.list(AuditLog) if row.input_ref == result.pipeline_run_id} == {
            "discovery",
            "normalise",
            "resolve",
            "detect",
            "route",
            "research",
            "score",
            "audit",
            "store",
        }
        count = len(db.list(Opportunity))
        with db.transaction():
            second = await service.run(max_queries=1, dry_run=False)
        assert second.status == "COMPLETED" and second.opportunities_created == 0
        assert len(db.list(Opportunity)) == count


async def test_preview_does_not_write_business_records(db):
    with (
        patch(
            "leados.services.live_discovery.ExaSearchProvider.search", AsyncMock(return_value=[document()])
        ),
        patch(
            "leados.services.live_discovery.FirecrawlCrawlerProvider.enrich_candidate", AsyncMock()
        ) as crawl,
    ):
        with db.transaction():
            summary = await LiveDiscoveryService(db).run(max_queries=1, dry_run=True)
        assert summary.status == "COMPLETED" and summary.opportunities_created == 0
        assert not db.list(Company) and not db.list(Opportunity)
        crawl.assert_not_called()


async def test_live_route_does_not_reacquire_storage_lock(db, monkeypatch):
    async def dependency():
        async with api_write_lock:
            with db.transaction():
                yield db

    monkeypatch.setitem(app.dependency_overrides, get_db, dependency)
    summary = SimpleNamespace(model_dump=lambda: {"status": "COMPLETED"})
    try:
        with patch("leados.api.LiveDiscoveryService.run", AsyncMock(return_value=summary)):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await asyncio.wait_for(
                    client.post("/pipeline/discover/live", json={"dry_run": True, "max_queries": 1}),
                    timeout=2,
                )
                assert response.status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_hubspot_upsert_does_not_duplicate_or_overwrite_existing(monkeypatch):
    monkeypatch.setattr(settings, "hubspot_access_token", "crm-token")
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer crm-token"
        return httpx.Response(200, json={"results": [{"id": "existing-company"}]})

    provider = HubSpotCRMProvider(httpx.MockTransport(handler))
    lead = {
        "id": "lead",
        "company": "Acme",
        "domain": "acme.com",
        "service": "AI assessment",
        "score": 90,
        "status": "New",
        "thesis": "Consider review",
    }
    assert (await provider.prepare(lead))["external_write"] is False
    result = await provider.sync(lead)
    assert result["status"] == "LINKED" and result["external_write"] is False
    assert len(requests) == 1 and requests[0].url.path.endswith("search")


def test_external_actions_block_synthetic_fixture(client, populated):
    lead = next(
        row for row in populated.list(Opportunity) if row.audit_status == "VERIFIED" and row.score >= 80
    )
    with (
        patch("leados.providers.future.contacts.ContactOutContactProvider.enrich", AsyncMock()) as enrich,
        patch("leados.providers.future.hubspot.HubSpotCRMProvider.sync", AsyncMock()) as sync,
    ):
        assert client.post(f"/opportunities/{lead.id}/contacts/enrich", json={}).status_code == 409
        assert client.post(f"/opportunities/{lead.id}/crm/sync", json={}).status_code == 409
        enrich.assert_not_called()
        sync.assert_not_called()


async def test_crm_requires_latest_human_approval_and_is_idempotent(db, client):
    with db.transaction():
        row = document()
        row["snippet"] = "Acme Systems is seeking external consulting support for privacy assessment."
        await Pipeline(db).run_documents([row], live=True)
    lead = next(row for row in db.list(Opportunity) if row.score >= 70 and row.audit_status == "VERIFIED")
    with patch(
        "leados.providers.future.hubspot.HubSpotCRMProvider.sync",
        AsyncMock(return_value={"status": "CREATED", "company_id": "hub-company", "external_write": True}),
    ) as sync:
        assert client.post(f"/opportunities/{lead.id}/crm/sync", json={}).status_code == 409
        assert (
            client.post(f"/opportunities/{lead.id}/approve", json={"reviewer": "Reviewer"}).status_code == 200
        )
        response = client.post(f"/opportunities/{lead.id}/crm/sync", json={})
        assert response.status_code == 200 and response.json()["email_sent"] is False
        assert client.post(f"/opportunities/{lead.id}/crm/sync", json={}).json()["status"] == "ALREADY_SYNCED"
        sync.assert_awaited_once()
        assert (
            client.post(f"/opportunities/{lead.id}/reject", json={"reviewer": "Reviewer"}).status_code == 200
        )
        assert client.post(f"/opportunities/{lead.id}/crm/sync", json={}).status_code == 409


def test_exa_unknown_dates_and_sources_are_not_invented():
    provider = ExaSearchProvider(api_key="test", enabled=True)
    response = SimpleNamespace(
        results=[],
        output=SimpleNamespace(content={"events": [{"company_name": "Acme", "event_summary": "Invented"}]}),
    )
    assert provider._format_results_to_documents(response) == []
    response.results = [
        SimpleNamespace(
            url="https://publisher.net/article",
            title="Acme appoints counsel",
            highlights=["Acme appoints counsel"],
            published_date=None,
            author=None,
        )
    ]
    doc = provider._format_results_to_documents(response)[0]
    assert doc["published_date"] is None and doc["company"]["domain"] is None


async def test_contact_enrichment_persists_valid_ids_and_deduplicates(db, client):
    with db.transaction():
        row = document()
        row["snippet"] = "Acme Systems is seeking external consulting support for privacy assessment."
        await Pipeline(db).run_documents([row], live=True)
    lead = next(row for row in db.list(Opportunity) if row.score >= 65 and row.audit_status == "VERIFIED")
    contact = {
        "person_name": "Test Counsel",
        "role": "General Counsel",
        "contact_email": "counsel@acme.com",
        "contact_source": "ContactOut",
        "contact_status": "FOUND_UNVERIFIED",
        "confidence": 0.7,
    }
    with (
        patch(
            "leados.services.contact_enrichment.ContactOutContactProvider.enrich",
            AsyncMock(return_value=[contact]),
        ) as enrich,
        patch(
            "leados.services.contact_enrichment.SnovioContactProvider.verify",
            AsyncMock(return_value={"counsel@acme.com": "VALIDATED"}),
        ),
    ):
        response = client.post(f"/opportunities/{lead.id}/contacts/enrich", json={})
        assert response.status_code == 200
        assert response.json()["contacts"][0]["contact_status"] == "VALIDATED"
        assert client.get(f"/opportunities/{lead.id}/contacts").json()[0]["person_name"] == "Test Counsel"
        assert (
            client.get(f"/opportunities/{lead.id}/contacts").json()[0]["contact_email"] == "counsel@acme.com"
        )
        assert client.post(f"/opportunities/{lead.id}/contacts/enrich", json={}).json()["status"] == "CACHED"
        enrich.assert_awaited_once()


async def test_openai_failure_preserves_lead_for_research(db):
    providers = get_providers()
    providers.llm = OpenAILLMProvider()
    with patch.object(
        providers.llm,
        "research",
        AsyncMock(side_effect=ProviderError("openai_credits_required", retryable=False)),
    ) as research:
        with db.transaction():
            run = await Pipeline(db, providers=providers).run_documents([document()])
        assert run.status == "PARTIAL" and run.error == "openai_credits_required"
        assert db.list(Opportunity) and all(
            lead.human_status == "NEEDS_RESEARCH" for lead in db.list(Opportunity)
        )
        research.assert_awaited_once()


async def test_exa_auth_failure_never_falls_back_to_another_paid_call(tmp_path, monkeypatch):
    monkeypatch.setattr("leados.providers.future.exa.provider_cache", ProviderCache(tmp_path / "cache.json"))
    error = Exception("contains-secret")
    error.status_code = 401
    provider = ExaSearchProvider(api_key="test", enabled=True)
    provider._client = MagicMock()
    provider._client.search.side_effect = error
    with pytest.raises(ProviderError, match="exa_invalid_credentials"):
        await provider.search(query="query", force_refresh=True)
    assert provider._client.search.call_count == 1
