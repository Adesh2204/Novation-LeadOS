"""Storage acceptance: real adapter logic exercised through a network-free client."""

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from uuid import UUID

import httpx
import pytest

from leados.config import Settings
from leados.engine import resolve_company
from leados.knowledge import knowledge
from leados.pipeline import Pipeline
from leados.providers.base import ProviderError
from leados.safety import guarded_send, is_suppressed
from leados.schemas import CompanyInput
from leados.storage.base import StorageError
from leados.storage.fake_google_client import MockGoogleSheetsClient
from leados.storage.google_client import GoogleSheetsClient
from leados.storage.google_sheets import GoogleSheetsStorageProvider
from leados.storage.mock import MockStorageProvider
from leados.storage.records import (
    AuditLog,
    Company,
    FeedbackEvent,
    HumanReview,
    Opportunity,
    OutreachDraft,
    ProviderRun,
    Signal,
    SourceDocument,
    Suppression,
)
from leados.storage.repositories import CompanyRepository
from leados.storage.setup import initialize_workbook
from leados.storage.transfer import export_data, import_data
from leados.storage.workbook import REQUIRED_TABS, SCHEMAS, SHEETS_SCOPE


@pytest.fixture
def sheets(tmp_path):
    client = MockGoogleSheetsClient()
    initialize_workbook(client)
    settings = Settings(
        storage_outbox_path=str(tmp_path / "outbox.json"),
        storage_lock_path=str(tmp_path / "lock"),
        sheets_max_attempts=3,
    )
    storage = GoogleSheetsStorageProvider(client, settings)
    with storage.transaction():
        knowledge.seed(storage)
    return storage, client


def company_input(name="Atlas Test", domain="atlas-test.example"):
    return CompanyInput(
        name=name,
        domain=domain,
        country="India",
        sector="SaaS",
        employee_range="201-500",
        funding_stage="Series B",
        locations=["Bengaluru"],
        description="Synthetic company",
    )


def raw_row(client, tab, oid):
    rows = client.tabs[tab]["rows"]
    schema = SCHEMAS[tab]
    index = rows[0].index(schema.aliases.get("id", "id"))
    return next(row for row in rows[1:] if len(row) > index and row[index] == oid)


def test_all_schemas_have_required_columns_and_uuid_ids(sheets):
    storage, client = sheets
    assert len(REQUIRED_TABS) == 16 and set(REQUIRED_TABS) <= set(client.tabs)
    assert len(client.tabs) == 19
    assert all(client.tabs[tab]["rows"][0] == schema.headers for tab, schema in SCHEMAS.items())
    assert len(storage.list(Signal)) == 114
    for signal in storage.list(Signal):
        UUID(signal.id[-36:])


def test_create_update_references_uniqueness_and_repository(db):
    repository = CompanyRepository(db)
    with db.transaction():
        company, created = resolve_company(db, company_input())
    assert created
    UUID(company.id[-36:])
    original_id = company.id
    with db.transaction(refresh=True):
        repository.update(original_id, {"description": "Updated through repository"})
    assert repository.get(original_id).description == "Updated through repository"
    with db.transaction():
        duplicate, created = resolve_company(db, company_input("Atlas Test Ltd", "www.atlas-test.example"))
    assert not created and duplicate.id == original_id
    with pytest.raises(StorageError, match="duplicate_record"):
        db.add(
            Company(
                **{**company.model_dump(exclude={"id"}), "id": "cmp_11111111-1111-4111-8111-111111111111"}
            )
        )
    with pytest.raises(StorageError, match="missing_reference"):
        db.add(Suppression(company_id="cmp_11111111-1111-4111-8111-111111111111", do_not_contact=True))
    with pytest.raises(StorageError, match="immutable_identity"):
        repository.update(original_id, {"id": "changed"})


async def test_google_rows_support_all_nine_verticals_and_official_scores(sheets):
    storage, client = sheets
    start = len([c for c in client.calls if c["method"] == "batch_update"])
    with storage.transaction(refresh=True):
        run = await Pipeline(storage, as_of=date(2026, 10, 6)).run()
    assert run.metrics["successful"] == 44
    assert len([c for c in client.calls if c["method"] == "batch_update"]) - start == 1
    assert len(client.tabs["OPPORTUNITIES"]["rows"]) == 45
    storage._loaded = False
    assert len({o.vertical_id for o in storage.list(Opportunity)}) == 9
    assert not storage.validation_errors
    atlas = storage.first(Company, canonical_name="Atlas AI Systems")
    opportunities = storage.list(Opportunity, company_id=atlas.id)
    assert {o.vertical_id for o in opportunities} == {"ai_governance", "privacy"}
    assert all(o.score == 96 for o in opportunities)
    headers = client.tabs["OPPORTUNITIES"]["rows"][0]
    for row in client.tabs["OPPORTUNITIES"]["rows"][1:]:
        parts = sum(
            int(row[headers.index(k)])
            for k in [
                "need_score",
                "icp_fit_score",
                "trigger_strength_score",
                "recency_score",
                "mandate_value_score",
                "decision_maker_score",
                "expertise_match_score",
                "evidence_quality_score",
            ]
        )
        assert parts == row[headers.index("total_score")]


def test_reordered_rows_and_headers_keep_ids_and_extra_cells(sheets):
    storage, client = sheets
    with storage.transaction():
        one, _ = resolve_company(storage, company_input())
        two, _ = resolve_company(storage, company_input("Second Co", "second.example"))
    rows = client.tabs["COMPANIES"]["rows"]
    rows[1:] = list(reversed(rows[1:]))
    # A user-added column/formula is outside the backend-owned ranges.
    rows[0].insert(3, "human_note")
    for row in rows[1:]:
        row.insert(3, "=1+1")
    # Move canonical_name header and its cells to a new position too.
    pos = rows[0].index("canonical_name")
    for row in rows:
        row.append(row.pop(pos))
    with storage.transaction():
        storage.update(Company, one.id, {"description": "UUID-targeted update"})
    storage._loaded = False
    assert storage.get(Company, one.id).description == "UUID-targeted update"
    assert storage.get(Company, two.id).description == "Synthetic company"
    assert all(row[rows[0].index("human_note")] == "=1+1" for row in client.tabs["COMPANIES"]["rows"][1:])
    assert any(e["code"] == "unexpected_column" for e in storage.validation_errors)
    assert any(a.module == "storage_validation" for a in storage.list(AuditLog))


def test_setup_is_idempotent_and_preserves_existing_rows(sheets):
    storage, client = sheets
    with storage.transaction():
        company, _ = resolve_company(storage, company_input())
    before = copy.deepcopy(client.tabs["COMPANIES"]["rows"])
    result = initialize_workbook(client)
    assert result["created_tabs"] == [] and not result["existing_data_deleted"]
    assert client.tabs["COMPANIES"]["rows"] == before
    requests = client.calls[-1]["requests"]
    assert any("setBasicFilter" in r for r in requests)
    assert any("setDataValidation" in r for r in requests)
    assert storage.get(Company, company.id)


@pytest.mark.parametrize("failure", ["quota_exceeded", "storage_timeout", "google_api_unavailable"])
def test_bounded_retry_and_no_duplicate_after_transient_failure(sheets, failure):
    storage, client = sheets
    with storage.transaction():
        company, _ = resolve_company(storage, company_input())
        client.failures = [failure]
    assert storage.metrics["retries"] == 1
    assert len(client.tabs["COMPANIES"]["rows"]) == 2
    assert not storage.outbox.exists()


def test_ambiguous_timeout_reconciles_commit_marker(sheets):
    storage, client = sheets
    with storage.transaction():
        resolve_company(storage, company_input())
        client.fail_after_commit = True
    assert len(client.tabs["COMPANIES"]["rows"]) == 2
    assert storage.metrics["retries"] == 1 and not storage.outbox.exists()


def test_failed_write_outbox_recovers_without_losing_prior_records(sheets):
    storage, client = sheets
    with storage.transaction():
        first, _ = resolve_company(storage, company_input())
    with pytest.raises(StorageError, match="storage_timeout"):
        with storage.transaction():
            second, _ = resolve_company(storage, company_input("Second Co", "second.example"))
            client.failures = ["storage_timeout"] * 3
    assert storage.outbox.exists() and len(client.tabs["COMPANIES"]["rows"]) == 2
    recovered = GoogleSheetsStorageProvider(client, storage.config)
    assert recovered.recover()["recovered"]
    assert recovered.get(Company, first.id) and recovered.get(Company, second.id)
    assert len(client.tabs["COMPANIES"]["rows"]) == 3
    assert not recovered.outbox.exists()


@pytest.mark.parametrize("failure", ["authentication_failed", "permission_denied", "spreadsheet_not_found"])
def test_nonretryable_errors_are_structured_and_bounded(sheets, failure):
    storage, client = sheets
    client.failures = [failure]
    with pytest.raises(StorageError, match=failure):
        storage._ensure(refresh=True)
    assert storage.metrics["retries"] == 0


@pytest.mark.parametrize(
    "mutation,expected", [("missing_tab", "missing_sheet"), ("bad_header", "missing_column")]
)
def test_clear_missing_sheet_and_header_errors(sheets, mutation, expected):
    storage, client = sheets
    if mutation == "missing_tab":
        del client.tabs["OPPORTUNITIES"]
    else:
        client.tabs["OPPORTUNITIES"]["rows"][0].remove("total_score")
    with pytest.raises(StorageError, match=expected):
        storage._ensure(refresh=True)


@pytest.mark.parametrize(
    "column,value",
    [
        ("total_score", "not a number"),
        ("score_band", "SUPER HOT!!!!!"),
        ("human_status", "BOGUS"),
        ("company_id", ""),
        ("total_score", 12),
    ],
)
async def test_manual_corruption_is_quarantined_and_audited(sheets, column, value):
    storage, client = sheets
    with storage.transaction():
        await Pipeline(storage).run("Atlas AI Systems")
    oid = storage.list(Opportunity)[0].id
    rows = client.tabs["OPPORTUNITIES"]["rows"]
    raw_row(client, "OPPORTUNITIES", oid)[rows[0].index(column)] = value
    with storage.transaction(refresh=True):
        assert storage.get(Opportunity, oid) is None
        assert len(storage.list(Opportunity)) == 1
        assert storage.validation_errors
    assert any(a.module == "storage_validation" and not a.success for a in storage.list(AuditLog))
    assert (
        len(client.tabs["OPPORTUNITIES"]["rows"]) == 3
    )  # Corrupted row is retained, never overwritten/deleted.


@pytest.mark.parametrize("column,value", [("assertion_type", "ALLEGATION"), ("content_hash", "0" * 64)])
async def test_source_edits_cannot_leave_unsupported_verified_opportunities(sheets, column, value):
    storage, client = sheets
    with storage.transaction():
        await Pipeline(storage).run("Atlas AI Systems")
    documents = storage.list(SourceDocument)
    headers = client.tabs["SOURCES"]["rows"][0]
    for document in documents:
        raw_row(client, "SOURCES", document.id)[headers.index(column)] = value
    with storage.transaction(refresh=True):
        assert not storage.list(Opportunity, audit_status="VERIFIED")
        assert storage.validation_errors
    assert any(a.module == "storage_validation" and not a.success for a in storage.list(AuditLog))
    assert len(client.tabs["SOURCES"]["rows"]) == len(documents) + 1


def test_duplicate_manual_row_detected_and_existing_data_retained(sheets):
    storage, client = sheets
    with storage.transaction():
        company, _ = resolve_company(storage, company_input())
    client.tabs["COMPANIES"]["rows"].append(copy.deepcopy(client.tabs["COMPANIES"]["rows"][1]))
    with storage.transaction(refresh=True):
        assert storage.get(Company, company.id) is None
        assert any(e["code"] == "duplicate_record" for e in storage.validation_errors)
    assert len(client.tabs["COMPANIES"]["rows"]) == 3


def test_concurrent_stale_update_is_blocked(sheets):
    storage, client = sheets
    with storage.transaction():
        company, _ = resolve_company(storage, company_input())
    row = raw_row(client, "COMPANIES", company.id)
    row[client.tabs["COMPANIES"]["rows"][0].index("description")] = "Human update"
    with pytest.raises(StorageError, match="concurrent_edit_conflict"):
        with storage.transaction():
            storage.update(Company, company.id, {"description": "Stale worker update"})
    assert row[client.tabs["COMPANIES"]["rows"][0].index("description")] == "Human update"


def test_concurrent_workers_serialize_critical_writes(sheets):
    storage, client = sheets

    def worker(_):
        provider = GoogleSheetsStorageProvider(client, storage.config)
        with provider.transaction(refresh=True):
            company, _ = resolve_company(provider, company_input())
            return company.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(worker, range(2)))
    assert len(set(ids)) == 1 and len(client.tabs["COMPANIES"]["rows"]) == 2


async def test_review_feedback_and_provider_run_history_append(sheets):
    storage, client = sheets
    with storage.transaction():
        run = await Pipeline(storage).run("Atlas AI Systems")
    rows_before = copy.deepcopy(client.tabs["PROVIDER_RUNS"]["rows"])
    with storage.transaction(refresh=True):
        run = storage.get(ProviderRun, run.id)
        run.duration_ms += 1
    assert client.tabs["PROVIDER_RUNS"]["rows"][: len(rows_before)] == rows_before
    assert len(client.tabs["PROVIDER_RUNS"]["rows"]) == len(rows_before) + 1
    storage._loaded = False
    assert storage.get(ProviderRun, run.id).duration_ms == run.duration_ms


async def test_manual_approved_cell_does_not_create_approval(db):
    with db.transaction():
        await Pipeline(db).run("Atlas AI Systems")
    opportunity = db.first(Opportunity, audit_status="VERIFIED")
    opportunity.human_status = "APPROVED"
    draft = db.first(OutreachDraft, opportunity_id=opportunity.id)
    draft.human_approved = True

    class NeverEmail:
        async def send(self, *args):
            raise AssertionError("Email must never be called")

    with pytest.raises(ProviderError, match="approved_review_required"):
        await guarded_send(db, opportunity, "", Settings(enable_email_send=True), NeverEmail())


def test_domain_suppression_does_not_require_company_id(db):
    with db.transaction():
        company, _ = resolve_company(db, company_input())
        db.add(Suppression(domain=company.domain, reason="Domain exclusion"))
    assert is_suppressed(db, company.id)


async def test_export_import_keeps_ids_scores_reviews_and_feedback(db, tmp_path):
    with db.transaction():
        await Pipeline(db).run("Atlas AI Systems")
        opportunity = db.first(Opportunity, audit_status="VERIFIED")
        db.add(HumanReview(opportunity_id=opportunity.id, reviewer="Test", decision="MONITOR", notes=""))
        db.add(
            FeedbackEvent(
                opportunity_id=opportunity.id,
                status="Meeting",
                reason=None,
                notes="",
                buyer_role="CFO",
                score_snapshot=opportunity.score,
                score_version=opportunity.score_version,
                knowledge_version=opportunity.knowledge_version,
                signal_version=opportunity.signal_version,
            )
        )
    output = tmp_path / "export"
    export_data(db, output)
    target = MockStorageProvider(tmp_path / "imported.json")
    data = json.loads((output / "leados.json").read_text())
    import_data(target, data)
    assert target.get(Opportunity, opportunity.id).score == opportunity.score
    assert len(target.list(HumanReview)) == 1 and len(target.list(FeedbackEvent)) == 1
    assert len(list(output.glob("*.csv"))) == len(data["entities"])
    assert import_data(target, data)["created"] == 0


async def test_legacy_mock_run_snapshots_receive_stable_uuid_ids(tmp_path):
    path = tmp_path / "legacy.json"
    source = MockStorageProvider(path)
    with source.transaction():
        knowledge.seed(source)
        await Pipeline(source).run("Atlas AI Systems")
    legacy = json.loads(path.read_text())
    for snapshot in legacy["provider_run_history"]:
        snapshot.pop("snapshot_id")
    path.write_text(json.dumps(legacy))
    source = MockStorageProvider(path)
    export_data(source, tmp_path / "first")
    payload = json.loads((tmp_path / "first/leados.json").read_text())
    ids = {row["snapshot_id"] for row in payload["provider_run_history"]}
    assert len(ids) == len(legacy["provider_run_history"])
    for oid in ids:
        UUID(oid[-36:])
    export_data(MockStorageProvider(path), tmp_path / "second")
    repeated = json.loads((tmp_path / "second/leados.json").read_text())
    assert {row["snapshot_id"] for row in repeated["provider_run_history"]} == ids
    client = MockGoogleSheetsClient()
    initialize_workbook(client)
    target = GoogleSheetsStorageProvider(
        client,
        Settings(storage_outbox_path=str(tmp_path / "outbox.json"), storage_lock_path=str(tmp_path / "lock")),
    )
    import_data(target, payload)
    target._ensure(refresh=True)
    assert {row["snapshot_id"] for row in target.provider_history} == ids
    assert import_data(target, payload)["created"] == 0


def test_real_client_uses_minimum_scope_and_batched_rest_without_network(monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"valueRanges": [{"values": [["id"], ["uuid"]]}]})
        return httpx.Response(200, json={"replies": []})

    config = Settings(google_sheets_enabled=True, google_spreadsheet_id="test-spreadsheet")
    client = GoogleSheetsClient(
        config, transport=httpx.MockTransport(handle), token_provider=lambda: "synthetic-token"
    )
    assert client.batch_read(["'COMPANIES'!A1:B10"])[0][1] == ["uuid"]
    client.batch_update([{"appendCells": {"sheetId": 1, "rows": [], "fields": "userEnteredValue"}}])
    assert len(requests) == 2
    assert requests[0].url.path.endswith("/values:batchGet")
    assert requests[1].url.path.endswith(":batchUpdate")
    assert SHEETS_SCOPE == "https://www.googleapis.com/auth/spreadsheets"
    assert all(r.headers["Authorization"] == "Bearer synthetic-token" for r in requests)
    client.close()


@pytest.mark.parametrize(
    "status,expected,attempts",
    [
        (429, "quota_exceeded", 3),
        (503, "google_api_unavailable", 3),
        (403, "permission_denied", 1),
        (404, "spreadsheet_not_found", 1),
    ],
)
def test_real_rest_errors_never_expose_response_secrets(monkeypatch, status, expected, attempts):
    calls = 0
    monkeypatch.setattr("leados.storage.google_client.time.sleep", lambda _: None)

    def handle(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": {"message": "private-key-secret"}})

    client = GoogleSheetsClient(
        Settings(google_sheets_enabled=True, google_spreadsheet_id="test"),
        transport=httpx.MockTransport(handle),
        token_provider=lambda: "synthetic",
    )
    with pytest.raises(StorageError, match=expected) as failure:
        client.metadata()
    assert "private-key-secret" not in str(failure.value) and calls == attempts


@pytest.mark.parametrize("target_kind", ["mock", "google_sheets"])
async def test_portable_transfer_preserves_all_run_snapshots(sheets, tmp_path, target_kind):
    storage, client = sheets
    run = Pipeline(storage).start("Atlas AI Systems")
    for stage in [
        "discovery",
        "normalise",
        "resolve",
        "detect",
        "route",
        "research",
        "score",
        "audit",
        "store",
    ]:
        await Pipeline(storage).advance(run, stage)
    export_data(storage, tmp_path / "portable")
    payload = json.loads((tmp_path / "portable/leados.json").read_text())
    history_ids = {h["snapshot_id"] for h in payload["provider_run_history"]}
    assert len(history_ids) == 10
    if target_kind == "mock":
        target = MockStorageProvider(tmp_path / "target.json")
    else:
        fake = MockGoogleSheetsClient()
        initialize_workbook(fake)
        target = GoogleSheetsStorageProvider(
            fake,
            Settings(
                storage_outbox_path=str(tmp_path / "target-outbox.json"),
                storage_lock_path=str(tmp_path / "target.lock"),
            ),
        )
    import_data(target, payload)
    target._loaded = False
    assert target.get(ProviderRun, run.id).stage == "store"
    assert {h["snapshot_id"] for h in target.provider_history} == history_ids
    assert import_data(target, payload)["created"] == 0
    assert len(target.provider_history) == 10


async def test_quarantined_opportunity_cannot_be_inserted_again(sheets):
    storage, client = sheets
    with storage.transaction():
        await Pipeline(storage).run("Atlas AI Systems")
    opportunity = storage.list(Opportunity)[0]
    row = raw_row(client, "OPPORTUNITIES", opportunity.id)
    row[client.tabs["OPPORTUNITIES"]["rows"][0].index("total_score")] = "bad"
    with storage.transaction(refresh=True):
        run = await Pipeline(storage).run("Atlas AI Systems")
    assert run.metrics["opportunities_created"] == 0
    assert run.metrics["failed"] == 1
    assert len(client.tabs["OPPORTUNITIES"]["rows"]) == 3


async def test_quarantined_company_isolated_without_duplicates(sheets):
    storage, client = sheets
    with storage.transaction():
        await Pipeline(storage).run("Atlas AI Systems")
    company = storage.first(Company, canonical_name="Atlas AI Systems")
    row = raw_row(client, "COMPANIES", company.id)
    row[client.tabs["COMPANIES"]["rows"][0].index("canonical_name")] = ""
    with storage.transaction(refresh=True):
        run = await Pipeline(storage).run("Atlas AI Systems")
    assert run.status == "PARTIAL" and run.metrics["companies_discovered"] == 0
    assert len(client.tabs["COMPANIES"]["rows"]) == 2


def test_api_write_failure_is_reported_before_success_response(client, db, monkeypatch):
    def fail(changes):
        raise StorageError("simulated_storage_outage")

    monkeypatch.setattr(db, "_persist", fail)
    response = client.post("/pipeline/process", json={"company": "Atlas AI Systems"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "simulated_storage_outage"
    assert not db.list(Opportunity)


def test_storage_health_reports_selected_provider_without_credentials(client, db, monkeypatch):
    monkeypatch.setattr("leados.api.runtime_storage", lambda: db)
    response = client.get("/storage/health")
    assert response.status_code == 200 and response.json()["provider"] == db.name
    assert response.json()["connected"] is True
    assert "private_key" not in response.text


def test_core_modules_never_import_vendor_or_sql_storage():
    import ast

    from leados.config import ROOT

    for name in ["api", "cli", "engine", "knowledge", "pipeline", "safety"]:
        tree = ast.parse((ROOT / "backend/leados" / f"{name}.py").read_text())
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert not any(
            m.startswith(("sqlalchemy", "leados.db", "leados.models", "google.", "leados.storage.google"))
            for m in imports
        )
