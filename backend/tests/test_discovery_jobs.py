import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest

from leados.api import app, dashboard_state
from leados.config import ROOT, settings
from leados.providers.base import ProviderError
from leados.providers.cache import ProviderCache
from leados.providers.factory import get_providers
from leados.schemas import LiveDiscoveryInput
from leados.services.discovery_jobs import DiscoveryJobs
from leados.services.discovery_results import DISCOVERY_COLUMNS, DISCOVERY_TAB, discovery_rows
from leados.services.live_discovery import LiveDiscoveryService
from leados.services.master_view_sync import application_storage, master_view_status
from leados.storage.base import StorageError
from leados.storage.factory import get_db
from leados.storage.google_sheets import GoogleSheetsStorageProvider
from leados.storage.records import Company, Opportunity, ProviderRun


def sample():
    return deepcopy(json.loads((ROOT / "fixtures/market.json").read_text())["documents"][0])


def company(name):
    return Company(
        canonical_name=name,
        identity_key=name.lower(),
        country="Unknown",
        sector="Unknown",
        employee_range="Unknown",
        funding_stage="Unknown",
        locations=[],
        description="Test company",
    )


def test_read_snapshot_only_publishes_commits(db):
    view = db.read_view()
    with db.transaction():
        db.add(company("Pending"))
        assert not db.read_view().list(Company)
    assert len(db.read_view().list(Company)) == 1
    assert not view.list(Company)
    with pytest.raises(StorageError, match="read_only_snapshot"):
        db.read_view().add(company("Forbidden"))
    with pytest.raises(ValueError):
        with db.transaction():
            db.add(company("Rollback"))
            raise ValueError("rollback")
    assert len(db.read_view().list(Company)) == 1


def test_atomic_daily_budget_under_parallel_calls(tmp_path):
    cache = ProviderCache(tmp_path / "cache.json")
    with ThreadPoolExecutor(max_workers=8) as pool:
        reserved = list(pool.map(lambda _: cache.reserve_call("exa", 3), range(20)))
    assert sum(reserved) == cache.get_daily_usage("exa") == 3


async def test_parallel_search_is_bounded_and_keeps_stable_order(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "live_provider_concurrency", 2)
    monkeypatch.setattr(
        "leados.services.live_discovery.provider_cache", ProviderCache(tmp_path / "cache.json")
    )
    active = peak = 0
    service = LiveDiscoveryService(db)
    monkeypatch.setattr(settings, "max_exa_searches_per_run", 4)
    queries = service._select_queries(max_queries=4)

    async def search(self, company=None, query=None):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.025)
        active -= 1
        doc = sample()
        doc["company"]["name"] = "Query " + str([q["query"] for q in queries].index(query))
        doc["source_url"] = "https://research.example/" + doc["company"]["name"].replace(" ", "-")
        return [doc]

    monkeypatch.setattr("leados.services.live_discovery.ExaSearchProvider.search", search)
    stages = []
    with db.transaction():
        summary = await service.run(
            max_queries=4, dry_run=True, progress=lambda item: stages.append(item.stage)
        )
    assert peak == 2
    assert summary.queries_completed == summary.queries_total == 4
    assert [r["company"] for r in summary.results] == ["Query 0", "Query 1", "Query 2", "Query 3"]
    assert not db.list(Company) and not db.list(Opportunity)
    assert db.get(ProviderRun, summary.run_id).state["discovery_results"] == summary.results
    assert "search" in stages and "screen" in stages


async def test_partial_search_error_preserves_successful_results(db, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "leados.services.live_discovery.provider_cache", ProviderCache(tmp_path / "cache.json")
    )
    search = AsyncMock(side_effect=[[sample()], ProviderError("exa_rate_limited", retryable=False)])
    monkeypatch.setattr("leados.services.live_discovery.ExaSearchProvider.search", search)
    with db.transaction():
        summary = await LiveDiscoveryService(db).run(max_queries=2, dry_run=True)
    assert summary.status == "PARTIAL" and summary.errors == 1 and len(summary.results) == 1


async def test_live_results_sync_even_without_new_opportunities(db, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "leados.services.live_discovery.provider_cache", ProviderCache(tmp_path / "cache.json")
    )
    monkeypatch.setattr(
        "leados.services.live_discovery.ExaSearchProvider.search", AsyncMock(return_value=[sample()])
    )
    with application_storage(db):
        summary = await LiveDiscoveryService(db).run(max_queries=1, dry_run=True)
    rows = discovery_rows(db)
    assert len(rows) == 1 and rows[0]["run_id"] == summary.run_id and rows[0]["preview"]
    displayed = dashboard_state(db.read_view())["discovery_results"]
    assert [{k: v for k, v in row.items() if k != "identity_status"} for row in displayed] == summary.results
    assert all(row["identity_status"] == "SOURCE_REPORTED" for row in displayed)
    if isinstance(db, GoogleSheetsStorageProvider):
        assert db.client.tabs[DISCOVERY_TAB]["rows"][0] == DISCOVERY_COLUMNS
        assert db.client.tabs[DISCOVERY_TAB]["rows"][1][1] == sample()["company"]["name"]
        assert not db.client.tabs[DISCOVERY_TAB]["properties"]["hidden"]
        assert master_view_status(db)["valid"]
        with application_storage(db):
            pass
        assert len(db.client.tabs[DISCOVERY_TAB]["rows"]) == 2
    else:
        saved = json.loads(db.path.with_name(db.path.stem + "-discovery-results.json").read_text())
        assert saved["rows"] == rows


async def test_background_job_keeps_api_responsive_and_deduplicates_start(db, tmp_path, monkeypatch):
    manager = DiscoveryJobs(tmp_path / "jobs")
    monkeypatch.setattr("leados.api.discovery_jobs", manager)
    monkeypatch.setattr("leados.services.discovery_jobs.runtime_storage", lambda: db)
    monkeypatch.setattr("leados.services.discovery_jobs.api_write_lock", asyncio.Lock())
    monkeypatch.setattr(
        "leados.services.live_discovery.provider_cache", ProviderCache(tmp_path / "cache.json")
    )
    started = threading.Event()
    release = threading.Event()

    async def search(self, company=None, query=None):
        started.set()
        await asyncio.to_thread(release.wait, 3)
        return [sample()]

    async def read_dependency():
        yield db.read_view()

    monkeypatch.setattr("leados.services.live_discovery.ExaSearchProvider.search", search)
    monkeypatch.setitem(app.dependency_overrides, get_db, read_dependency)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await asyncio.wait_for(
                client.post("/pipeline/discover/live/jobs", json={"dry_run": True, "max_queries": 1}), 1
            )
            assert response.status_code == 202
            job_id = response.json()["job_id"]
            assert await asyncio.to_thread(started.wait, 2)
            duplicate = await client.post(
                "/pipeline/discover/live/jobs", json={"dry_run": True, "max_queries": 1}
            )
            assert duplicate.json()["job_id"] == job_id
            state = await asyncio.wait_for(client.get("/dashboard/state"), 1)
            assert state.status_code == 200 and state.json()["metrics"]["opportunities"] == 0
            progress = await client.get("/pipeline/discover/live/jobs/" + job_id)
            assert progress.json()["status"] == "RUNNING"
            release.set()
            await asyncio.gather(*manager.tasks)
            completed = (await client.get("/pipeline/discover/live/jobs/" + job_id)).json()
            assert completed["status"] == "COMPLETED" and completed["sheets_synced"]
            assert len((await client.get("/dashboard/state")).json()["discovery_results"]) == 1
            assert manager.latest()["job_id"] == job_id
            restored = DiscoveryJobs(tmp_path / "jobs")
            assert restored.latest()["status"] == "COMPLETED"
    finally:
        release.set()
        app.dependency_overrides.pop(get_db, None)


def test_restart_marks_unfinished_run_without_replaying_paid_work(tmp_path):
    from leados.storage.master_view_writer import atomic_json

    path = tmp_path / "jobs"
    atomic_json(
        path / "job_test.json",
        {"job_id": "job_test", "status": "RUNNING", "created_at": "2026-10-08", "stage": "search"},
    )
    manager = DiscoveryJobs(path)
    assert manager.latest()["status"] == "FAILED"
    assert manager.latest()["error"] == "server_restarted"
    assert not manager.tasks


async def test_parallel_research_keeps_scores_and_stage_order(db, monkeypatch):
    from datetime import date

    from leados.pipeline import Pipeline
    from leados.providers.mock.llm import MockLLMProvider

    active = peak = 0

    class SlowResearch(MockLLMProvider):
        async def research(self, context):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.015)
            active -= 1
            return await super().research(context)

    monkeypatch.setattr(settings, "live_provider_concurrency", 2)
    providers = get_providers()
    providers.llm = SlowResearch()
    from leados.storage.mock import MockStorageProvider

    sequential = MockStorageProvider()
    with sequential.transaction():
        reference = await Pipeline(sequential, as_of=date(2026, 10, 6)).run_documents([sample()])
    with db.transaction():
        run = await Pipeline(db, providers=providers, as_of=date(2026, 10, 6)).run_documents([sample()])
    assert peak == 2
    assert run.status == reference.status and run.stage == "store"
    expected = sorted((o.vertical_id, o.score, o.audit_status) for o in sequential.list(Opportunity))
    assert sorted((o.vertical_id, o.score, o.audit_status) for o in db.list(Opportunity)) == expected


async def test_parallel_embedding_requests_share_cached_vectors():
    from types import SimpleNamespace

    from leados.providers.future.openai import OpenAIEmbeddingProvider

    async def create(**kwargs):
        await asyncio.sleep(0.02)
        return SimpleNamespace(
            data=[SimpleNamespace(index=i, embedding=[float(i), 1.0]) for i in range(len(kwargs["input"]))]
        )

    client = SimpleNamespace(embeddings=SimpleNamespace(create=AsyncMock(side_effect=create)))
    provider = OpenAIEmbeddingProvider(client)
    outputs = await asyncio.gather(*(provider.embed(["same query", "same service"]) for _ in range(4)))
    assert outputs == [outputs[0]] * 4
    assert client.embeddings.create.call_count == 1


async def test_projection_failure_preserves_committed_data_and_reports_pending(db, tmp_path, monkeypatch):
    manager = DiscoveryJobs(tmp_path / "jobs")
    monkeypatch.setattr("leados.services.discovery_jobs.api_write_lock", asyncio.Lock())
    monkeypatch.setattr(
        "leados.services.live_discovery.provider_cache", ProviderCache(tmp_path / "cache.json")
    )
    monkeypatch.setattr(
        "leados.services.live_discovery.ExaSearchProvider.search", AsyncMock(return_value=[sample()])
    )

    def fail(storage):
        raise StorageError("storage_timeout")

    monkeypatch.setattr("leados.services.discovery_results.sync_discovery_results", fail)
    job = manager.start(LiveDiscoveryInput(dry_run=True, max_queries=1), db)
    await asyncio.gather(*manager.tasks)
    result = manager.jobs[job["job_id"]]
    assert result["status"] == "PARTIAL" and not result["sheets_synced"]
    assert result["error"] == "sheets_projection_pending"
    assert len(dashboard_state(db.read_view())["discovery_results"]) == 1


async def test_company_ceiling_retains_unprocessed_sources(db, tmp_path, monkeypatch):
    docs = []
    for n in range(3):
        doc = sample()
        name = "Company " + str(n)
        doc["snippet"] = doc["snippet"].replace(doc["company"]["name"], name)
        doc["company"]["name"] = name
        doc["source_url"] = f"https://research.example/company-{n}"
        docs.append(doc)
    monkeypatch.setattr(
        "leados.services.live_discovery.provider_cache", ProviderCache(tmp_path / "cache.json")
    )
    monkeypatch.setattr(
        "leados.services.live_discovery.ExaSearchProvider.search", AsyncMock(return_value=docs)
    )
    with db.transaction():
        summary = await LiveDiscoveryService(db).run(max_queries=1, max_companies=1, dry_run=True)
    assert len(summary.results) == 3
    assert summary.candidates_skipped_limit == 2
    assert [row["status"] for row in summary.results] == [
        "PREVIEW",
        "SKIPPED_COMPANY_LIMIT",
        "SKIPPED_COMPANY_LIMIT",
    ]
    assert not db.list(Company)
    assert (
        LiveDiscoveryService(db).estimate(max_queries=100, max_companies=500).queries_to_run
        <= settings.max_exa_searches_per_run
    )


def test_large_research_projection_uses_bounded_idempotent_batches(db, monkeypatch):
    if not isinstance(db, GoogleSheetsStorageProvider):
        return
    from leados.services.discovery_results import sync_discovery_results

    rows = [
        {
            "run_id": "run-large",
            "company": f"Company {n}",
            "source_url": f"https://sources.example/{n}",
            "published_date": "2026-10-08",
            "status": "PREVIEW",
            "relevance": 0.8,
            "reason": "Test source",
            "source_excerpt": "Evidence " * 150,
            "opportunity_ids": "",
            "preview": True,
            "retrieved_at": "2026-10-08T12:00:00+00:00",
            "record_origin": "LIVE",
            "organization_role": "UNCERTAIN",
            "service_demand": False,
            "commercial_fit": "UNVERIFIED",
            "qualification_method": "RULE_BASED",
            "qualification_version": "2.0",
            "firecrawl_decision": "NEEDS_ADDITIONAL_RESEARCH",
            "provider_score": "",
            "evidence_confidence": 0.5,
            "signal_confidence": 0,
        }
        for n in range(2000)
    ]
    monkeypatch.setattr("leados.services.discovery_results.discovery_rows", lambda storage: rows)
    result = sync_discovery_results(db)
    assert result["discovery_rows"] == 2000
    assert len(db.client.tabs[DISCOVERY_TAB]["rows"]) == 2001
    calls = len(db.client.calls)
    sync_discovery_results(db)
    assert not any(call["method"] == "batch_update" for call in db.client.calls[calls:])


async def test_natural_live_signal_keeps_source_in_google_overview(db):
    from datetime import date

    from leados.pipeline import Pipeline
    from leados.services.master_view import MasterViewService

    doc = sample()
    doc["published_date"] = date.today().isoformat()
    doc["company"]["name"] = "Acme Systems"
    doc["company"]["domain"] = "acme.com"
    doc["source_url"] = "https://acme.com/careers/dpo"
    doc["snippet"] = (
        "Acme Systems is hiring a Data Protection Officer to lead its privacy implementation programme."
    )
    doc["company_match"] = True
    with application_storage(db):
        run = await Pipeline(db).run_documents([doc], live=True)
    assert run.status == "COMPLETED"
    rows = MasterViewService(db.read_view()).build_rows()
    verified = [row for row in rows if row["source"] == doc["source_url"]]
    assert len(verified) == len(rows) == 1
    assert rows[0]["record_type"] == "POTENTIAL_PROSPECT"
    assert rows[0]["research_status"] == "POTENTIAL_PROSPECT"
    assert not rows[0]["opportunity_id"] and not db.list(Opportunity)
