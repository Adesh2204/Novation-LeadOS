"""Mock-only activation and read-only prospect integration regressions."""

import importlib.util
from datetime import date, timedelta

import pytest

from leados.api import dashboard_state
from leados.config import ROOT, Settings
from leados.knowledge import knowledge
from leados.pipeline import Pipeline
from leados.providers.cache import ProviderCache
from leados.services.live_activation import live_readiness
from leados.services.master_view import MasterViewService
from leados.services.master_view_sync import application_storage, master_view_status
from leados.services.prospects import live_prospects
from leados.storage.records import Company, Opportunity, SourceDocument


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def document(text=None):
    return {
        "company": {
            "name": "Example Bank",
            "domain": "bank.example",
            "country": "India",
            "sector": "BFSI",
            "employee_range": "1000+",
            "funding_stage": "Public",
            "locations": ["India"],
            "description": "Mocked research",
        },
        "source_url": "https://bank.example/careers/dpo",
        "source_name": "Example Bank Careers",
        "source_type": "company_website",
        "published_date": date.today().isoformat(),
        "snippet": text or "Example Bank is hiring a Data Protection Officer to lead its privacy programme.",
        "confidence": 0.85,
        "assertion_type": "FACT",
        "company_match": True,
        "conflict": False,
    }


async def save(db, doc):
    with application_storage(db):
        return await Pipeline(db).run_documents([doc], live=True)


async def test_dpo_prospect_dashboard_detail_and_master_without_opportunity(db, client):
    await save(db, document())
    prospects = live_prospects(db.read_view())
    assert len(prospects) == 1
    row = prospects[0]
    assert row["vertical_id"] == "privacy" and row["research_status"] == "POTENTIAL_PROSPECT"
    assert row["contact_status"] == "RECOMMENDED_ROLE_ONLY" and row["buyer_roles"]
    assert not db.list(Opportunity)
    assert dashboard_state(db.read_view())["prospects"] == prospects
    assert not dashboard_state(db.read_view(), "MOCK")["prospects"]
    assert not dashboard_state(db.read_view(), "MOCK")["discovery_results"]
    master = MasterViewService(db.read_view()).build_rows()
    assert master[0]["row_id"] == row["id"] and master[0]["score"] == ""
    assert master_view_status(db)["valid"]
    assert client.get(f"/prospects/{row['id']}").json()["source"] == row["source"]
    assert client.get("/prospects/unknown").status_code == 404


@pytest.mark.parametrize(
    "mutation",
    ["seller", "identity", "allegation", "conflict", "noise", "irrelevant", "low_confidence", "mock"],
)
async def test_unsuitable_sources_do_not_become_prospects(db, mutation):
    doc = document()
    if mutation == "seller":
        doc["snippet"] = (
            "Example Bank launches privacy software for customers, data protection officer hiring platform."
        )
    elif mutation == "identity":
        doc["snippet"] = "A different organisation is hiring a Data Protection Officer."
    elif mutation == "allegation":
        doc["assertion_type"] = "ALLEGATION"
    elif mutation == "conflict":
        doc["conflict"] = True
    elif mutation == "noise":
        doc["snippet"] += " Position closed."
    elif mutation == "irrelevant":
        doc["snippet"] = "Example Bank published general market commentary."
    elif mutation == "low_confidence":
        doc["confidence"] = 0.4
    if mutation == "mock":
        with application_storage(db):
            await Pipeline(db).run_documents([doc], live=False)
    else:
        await save(db, doc)
    assert not live_prospects(db.read_view())
    assert not MasterViewService(db.read_view()).build_rows()


@pytest.mark.parametrize("published", [None, "stale", "future"])
async def test_uncertain_timing_is_visible_needs_research_without_inventing_date(db, published):
    doc = document()
    doc["published_date"] = (
        None
        if published is None
        else (date.today() + timedelta(days=1 if published == "future" else -200)).isoformat()
    )
    await save(db, doc)
    prospect = live_prospects(db.read_view())[0]
    assert prospect["research_status"] == "NEEDS_RESEARCH"
    assert prospect["trigger_date"] == doc["published_date"]
    assert not db.list(Opportunity)


async def test_duplicate_source_and_repeat_keep_prospect_identity_and_projection(db):
    doc = document()
    await save(db, doc)
    first = live_prospects(db.read_view())
    counts = (len(db.list(Company)), len(db.list(SourceDocument)))
    await save(db, doc)
    assert counts == (len(db.list(Company)), len(db.list(SourceDocument)))
    assert [p["id"] for p in first] == [p["id"] for p in live_prospects(db.read_view())]
    assert master_view_status(db)["valid"] and master_view_status(db)["rows"] == 1


@pytest.mark.parametrize("vertical_id", list(knowledge.verticals))
async def test_primary_catalogue_signal_supports_every_vertical_without_nine_rows(db, vertical_id):
    signal = next(s for s in knowledge.signals.values() if s.vertical_ids[0] == vertical_id and s.keywords)
    doc = document(f"Example Bank reports {signal.keywords[0]} as a current business event.")
    await save(db, doc)
    prospects = live_prospects(db.read_view())
    assert len(prospects) == 1 and prospects[0]["vertical_id"] == vertical_id
    assert prospects[0]["recommended_service"] in knowledge.verticals[vertical_id].services


@pytest.mark.parametrize("block", ["enabled", "stop", "exa", "firecrawl", "budget", "email", "limits"])
def test_readiness_preserves_limits_stop_and_secrets(tmp_path, block):
    config = Settings(
        _env_file=None,
        exa_api_key="secret-exa",
        firecrawl_api_key="secret-fire",
        live_discovery_enabled=True,
        discovery_jobs_path=str(tmp_path),
    )
    cache = ProviderCache(tmp_path / "cache.json")
    if block == "enabled":
        config.live_discovery_enabled = False
    elif block == "stop":
        (tmp_path / "STOP_LIVE_DISCOVERY").touch()
    elif block == "exa":
        config.exa_api_key = ""
    elif block == "firecrawl":
        config.firecrawl_api_key = ""
    elif block == "budget":
        config.max_exa_calls_per_day = 0
    elif block == "email":
        config.enable_email_send = True
    elif block == "limits":
        config.max_firecrawl_pages_per_run = 0
    status = live_readiness(config, cache)
    assert not status["ready"] and status["blockers"] and "secret-" not in str(status)
    assert status["emergency_stop_available"] and not cache.cache_file.exists()


def test_rearm_updates_only_activation_and_preserves_unrelated_config_and_ledger(tmp_path):
    rearm = load_script("rearm_live_discovery")
    env = tmp_path / ".env"
    env.write_text(
        "# Config\nEXA_API_KEY=keep-secret\nLIVE_DISCOVERY_ENABLED=false\nENABLE_EMAIL_SEND=false\nMAX_EXA_CALLS_PER_DAY=50\n"
    )
    rearm.persist_activation(env)
    assert "EXA_API_KEY=keep-secret" in env.read_text()
    assert "MAX_EXA_CALLS_PER_DAY=50" in env.read_text()
    assert "LIVE_DISCOVERY_ENABLED=true" in env.read_text()
    assert env.stat().st_mode & 0o777 == 0o600
    marker = tmp_path / "STOP_LIVE_DISCOVERY"
    marker.touch()
    rearm.persist_activation(env)
    assert marker.exists()  # Only main's explicit checked enable may archive a stop.


def test_startup_verifies_identity_and_never_trusts_unknown_listener(monkeypatch):
    dev = load_script("dev")
    monkeypatch.setattr(dev, "read_json", lambda url: {"status": "ok", "signals": 114})
    assert dev.healthy(8000) and dev.healthy(3000)
    monkeypatch.setattr(dev, "read_json", lambda url: {"status": "ok"})
    assert not dev.healthy(8000)
    monkeypatch.setattr(dev, "listening", lambda port: True)
    monkeypatch.setattr(
        dev.subprocess, "Popen", lambda *a, **k: pytest.fail("Never replace an unknown listener")
    )
    assert dev.main() == 1


def test_rearm_detects_active_jobs_without_mutating_them(tmp_path):
    rearm = load_script("rearm_live_discovery")
    job = tmp_path / "job_active.json"
    job.write_text('{"status":"RUNNING"}')
    assert rearm.active_jobs(tmp_path) == ["job_active"]
    assert job.read_text() == '{"status":"RUNNING"}'


@pytest.mark.parametrize("pending", [False, True])
def test_checked_rearm_archives_stop_and_never_resets_usage(tmp_path, monkeypatch, pending):
    rearm = load_script("rearm_live_discovery")
    root = tmp_path / "app"
    root.mkdir()
    env = root / ".env"
    env.write_text("LIVE_DISCOVERY_ENABLED=false\nLIVE_PROVIDER_DRY_RUN=true\nENABLE_EMAIL_SEND=false\n")
    jobs = root / "jobs"
    jobs.mkdir()
    marker = jobs / "STOP_LIVE_DISCOVERY"
    marker.write_text("old authorised stop")
    ledger = root / "cache.json"
    ledger.write_text('{"daily_usage":{"2026-10-09":{"exa":4,"firecrawl":2}}}')
    before = ledger.read_bytes()
    config = Settings(
        _env_file=None,
        leados_storage="google_sheets",
        exa_api_key="test",
        firecrawl_api_key="test",
        discovery_jobs_path=str(jobs),
    )
    monkeypatch.setattr(rearm, "ROOT", root)
    monkeypatch.setattr(rearm, "DEFAULT_CACHE_FILE", ledger)
    monkeypatch.setattr(rearm, "ProviderCache", lambda: ProviderCache(ledger))
    monkeypatch.setattr(
        rearm,
        "Settings",
        lambda: config.model_copy(
            update={"live_discovery_enabled": "LIVE_DISCOVERY_ENABLED=true" in env.read_text()}
        ),
    )
    from contextlib import nullcontext

    class Storage:
        def transaction(self, **kwargs):
            return nullcontext()

        def health(self):
            return {"connected": True, "rows_valid": True, "pending_write": pending}

    monkeypatch.setattr(rearm, "build_storage", lambda cfg: Storage())
    monkeypatch.setattr(rearm.subprocess, "check_output", lambda *a, **k: "")
    monkeypatch.setattr("sys.argv", ["rearm", "--enable"])
    assert rearm.main() == (1 if pending else 0)
    assert ledger.read_bytes() == before
    if pending:
        assert marker.exists() and "LIVE_DISCOVERY_ENABLED=false" in env.read_text()
    else:
        assert not marker.exists() and "LIVE_DISCOVERY_ENABLED=true" in env.read_text()
        assert next((jobs / "archive").glob("STOP_LIVE_DISCOVERY-*")).read_text() == "old authorised stop"
        assert len(list((jobs / "archive").glob("settings-*.env.backup"))) == 1


async def test_restricted_source_preserves_valid_exa_prospect_evidence(db):
    doc = document()
    doc["provenance"] = {"source_error": "SOURCE_ACCESS_RESTRICTED"}
    await save(db, doc)
    row = live_prospects(db.read_view())[0]
    assert row["research_status"] == "NEEDS_RESEARCH"
    assert row["source_excerpt"] == doc["snippet"]
    assert row["evidence_status"] == "SOURCE_ACCESS_RESTRICTED"
    assert not db.list(Opportunity) and master_view_status(db)["valid"]


@pytest.mark.parametrize(
    "name", ["Request for Proposal for", "[PDF] Request for Proposal", "August 2026", "RFP 26"]
)
async def test_document_heading_stays_audit_only_and_does_not_crawl(db, monkeypatch, name):
    from unittest.mock import AsyncMock

    from leados.services.live_discovery import LiveDiscoveryService

    doc = document()
    doc["company"]["name"] = name
    doc["snippet"] = name + " is hiring a Data Protection Officer."
    monkeypatch.setattr(
        "leados.services.live_discovery.ExaSearchProvider.search", AsyncMock(return_value=[doc])
    )
    crawl = AsyncMock(side_effect=AssertionError("Identity must be checked before spending"))
    monkeypatch.setattr("leados.services.live_discovery.FirecrawlCrawlerProvider.enrich_candidate", crawl)
    with application_storage(db):
        summary = await LiveDiscoveryService(db).run(dry_run=False, max_queries=1)
    assert summary.results[0]["status"] == "SKIPPED_IDENTITY"
    assert summary.source_supported_companies == 0
    assert not db.list(Company) and not db.list(SourceDocument)
    crawl.assert_not_called()


async def test_recent_failure_cache_prevents_paid_retry_then_allows_later_recovery(monkeypatch):
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock

    from leados.providers.cache import provider_cache
    from leados.providers.future.firecrawl import FirecrawlCrawlerProvider
    from leados.providers.models import CrawledDocument

    doc = document()
    failed = CrawledDocument(
        url=doc["source_url"],
        canonical_url=doc["source_url"],
        title="",
        content="",
        content_hash="empty",
        provider="firecrawl",
        status="FAILED",
        metadata={"error": "timeout"},
    )
    provider = FirecrawlCrawlerProvider(enabled=True, dry_run=False)
    scrape = AsyncMock(return_value=failed)
    monkeypatch.setattr(provider, "_scrape_safe", scrape)
    first = await provider.enrich_candidate(doc)
    second = await provider.enrich_candidate(doc)
    assert first["crawler_error"] == second["crawler_error"] == "timeout"
    assert second["crawl_cache_reused"] and scrape.call_count == 1
    failed.retrieved_at = datetime.now(UTC) - timedelta(minutes=30)
    provider_cache.set_crawl(doc["source_url"], failed.model_dump(mode="json"))
    await provider.enrich_candidate(doc)
    assert scrape.call_count == 2


async def test_cache_only_job_never_calls_provider_on_miss(db, monkeypatch):
    from unittest.mock import AsyncMock

    from leados.services.live_discovery import LiveDiscoveryService

    search = AsyncMock(side_effect=AssertionError("No paid request allowed"))
    monkeypatch.setattr("leados.services.live_discovery.ExaSearchProvider.search", search)
    with application_storage(db):
        result = await LiveDiscoveryService(db).run(dry_run=False, max_queries=1, cache_only=True)
    assert result.exa_queries == result.firecrawl_requests == 0
    assert result.error == "search_cache_miss"
    search.assert_not_called()


async def test_cache_only_job_reuses_search_without_calling_extraction(db, monkeypatch):
    from unittest.mock import AsyncMock

    from leados.providers.cache import provider_cache
    from leados.services.live_discovery import LiveDiscoveryService

    service = LiveDiscoveryService(db)
    provider_cache.set_search(service._select_queries(max_queries=1)[0]["query"], [document()])
    scrape = AsyncMock(side_effect=AssertionError("No paid extraction allowed"))
    monkeypatch.setattr("leados.services.live_discovery.FirecrawlCrawlerProvider._scrape_safe", scrape)
    with application_storage(db):
        summary = await service.run(dry_run=False, max_queries=1, cache_only=True)
    assert summary.exa_queries == summary.firecrawl_requests == 0
    assert summary.exa_cache_hits == 1 and summary.results
    assert summary.results[0]["qualification"]["status"] == "NEEDS_RESEARCH"
    scrape.assert_not_called()


async def test_cache_only_repeat_preserves_saved_restriction_after_retry_cooldown(db, monkeypatch):
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock

    from leados.providers.cache import provider_cache
    from leados.services.live_discovery import LiveDiscoveryService

    doc = document()
    doc["crawler_error"] = "robots_or_access_restricted"
    await save(db, doc)
    source = db.list(SourceDocument)[0]
    source.retrieved_at = datetime.now(UTC) - timedelta(minutes=30)
    source.provenance["source_error"] = "robots_or_access_restricted"
    with db.transaction():
        db.update(
            SourceDocument,
            source.id,
            {
                "retrieved_at": source.retrieved_at,
                "provenance": source.provenance,
            },
        )
    service = LiveDiscoveryService(db)
    provider_cache.set_search(service._select_queries(max_queries=1)[0]["query"], [document()])
    scrape = AsyncMock(side_effect=AssertionError("Cache-only repeat cannot retry a paid scrape"))
    monkeypatch.setattr("leados.services.live_discovery.FirecrawlCrawlerProvider._scrape_safe", scrape)
    with application_storage(db):
        summary = await service.run(dry_run=False, max_queries=1, cache_only=True)
    assert summary.exa_queries == summary.firecrawl_requests == 0
    assert summary.firecrawl_cache_hits == 1
    assert summary.results[0]["firecrawl_decision"] == "ROBOTS_OR_ACCESS_RESTRICTED"
    assert db.list(SourceDocument)[0].provenance["source_error"] == "robots_or_access_restricted"
    scrape.assert_not_called()


async def test_main_ai_scope_wins_over_incidental_privacy_and_vendor_controls(db):
    doc = document(
        "Example Bank invites proposals for an independent AI governance assessment and AI risk assessment. The AI governance framework needs an AI policy and AI audit. The assessment covers incidental privacy risks and third-party assessment controls."
    )
    doc["title"] = "Example Bank AI governance assessment RFP"
    await save(db, doc)
    rows = live_prospects(db.read_view())
    assert len(rows) == 1 and rows[0]["vertical_id"] == "ai_governance"
    assert rows[0]["recommended_service"] in knowledge.verticals["ai_governance"].services


async def test_tied_unscored_sheet_rows_match_by_identity_not_google_blank_order(db):
    from leados.storage.google_sheets import GoogleSheetsStorageProvider
    from leados.storage.master_view_schema import MASTER_TAB

    if not isinstance(db, GoogleSheetsStorageProvider):
        return
    first = document()
    await save(db, first)
    second = document("Another Bank is hiring a Data Protection Officer.")
    second["company"]["name"] = "Another Bank"
    second["company"]["domain"] = "another.example"
    second["source_url"] = "https://another.example/careers/dpo"
    await save(db, second)
    tab = db.client.tabs[MASTER_TAB]["rows"]
    tab[1:] = list(reversed(tab[1:]))
    status = master_view_status(db)
    assert status["rows_match"] and status["ranking_valid"] and status["valid"]


async def test_sparse_unscored_master_rows_compact_without_losing_user_notes(db):
    from leados.services.master_view_sync import sync_master_view
    from leados.storage.google_sheets import GoogleSheetsStorageProvider
    from leados.storage.master_view_schema import MASTER_COLUMNS, MASTER_TAB

    if not isinstance(db, GoogleSheetsStorageProvider):
        return
    await save(db, document())
    second = document("Another Bank is hiring a Data Protection Officer.")
    second["company"].update(name="Another Bank", domain="another.example")
    second["source_url"] = "https://another.example/careers/dpo"
    await save(db, second)
    tab = db.client.tabs[MASTER_TAB]["rows"]
    original = [row.copy() for row in tab[1:3]]
    width = len(MASTER_COLUMNS)
    tab[0].append("Human notes")
    tab[1:] = [[], original[1] + ["Keep attached to this company"], *[[] for _ in range(10)], original[0]]
    assert not master_view_status(db)["rows_contiguous"]

    def canonical_records():
        # Repository-owned catalog instances get fresh load timestamps.
        return {kind: rows for kind, rows in db.snapshot().items() if kind not in {"Vertical", "Service"}}

    canonical = canonical_records()
    sync_master_view(db)
    assert canonical_records() == canonical
    status = master_view_status(db)
    assert status["valid"] and status["rows_contiguous"] and status["rows"] == 2
    assert tab[0][-1] == "Human notes"
    actual = db.client.tabs[MASTER_TAB]["rows"]
    attached = next(row for row in actual[1:3] if row[width:] == ["Keep attached to this company"])
    assert attached[:width] == original[1]
    writes = db.client.metrics["batch_writes"]
    sync_master_view(db)
    assert db.client.metrics["batch_writes"] == writes
