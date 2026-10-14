"""Presentation mechanics on explicitly selected development fixtures, using fake Sheets.
Production live-only projection contracts are tested in test_production_repair.
"""

import copy
import hashlib
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from leados.api import app
from leados.config import Settings
from leados.knowledge import knowledge
from leados.pipeline import Pipeline
from leados.services.master_view import MasterViewService
from leados.services.master_view_setup import setup_master_workbook
from leados.services.master_view_sync import (
    application_storage,
    master_view_status,
    sync_master_view,
    writer_for,
)
from leados.storage.base import StorageError
from leados.storage.factory import get_db
from leados.storage.fake_google_client import MockGoogleSheetsClient
from leados.storage.google_sheets import GoogleSheetsStorageProvider
from leados.storage.master_view_schema import MASTER_COLUMNS, MASTER_TAB, VISIBLE_COLUMNS
from leados.storage.master_view_writer import COLORS
from leados.storage.records import (
    Company,
    FeedbackEvent,
    HumanReview,
    Opportunity,
    OpportunityEvidence,
    OutreachDraft,
    SourceDocument,
)
from leados.storage.setup import initialize_workbook
from leados.storage.workbook import SCHEMAS


@pytest.fixture(autouse=True)
def development_projection(monkeypatch):
    # These legacy rendering/ownership tests exercise the fixture view deliberately.
    build = MasterViewService.build_rows
    monkeypatch.setattr(
        MasterViewService, "build_rows", lambda self, data_mode="MOCK": build(self, data_mode)
    )


@pytest.fixture
def overview(tmp_path):
    client = MockGoogleSheetsClient()
    client.tabs["Sheet1"] = {"id": 0, "rows": [["Keep these notes"], ["Existing data"]]}
    initialize_workbook(client)
    config = Settings(
        storage_outbox_path=str(tmp_path / "outbox.json"),
        storage_lock_path=str(tmp_path / "writer.lock"),
        show_technical_sheets=False,
    )
    storage = GoogleSheetsStorageProvider(client, config)
    with storage.transaction():
        knowledge.seed(storage)
    setup_master_workbook(client, config)
    return storage, client


def master_rows(client):
    return [
        dict(zip(MASTER_COLUMNS, row[:20], strict=False))
        for row in client.tabs[MASTER_TAB]["rows"][1:]
        if len(row) > 16 and row[16]
    ]


async def populate(storage):
    with application_storage(storage, refresh=True):
        return await Pipeline(storage, as_of=date(2026, 10, 6)).run()


def test_master_creation_visibility_helpers_formatting_and_preservation(overview):
    storage, client = overview
    assert list(client.tabs)[0] == MASTER_TAB
    assert client.tabs[MASTER_TAB]["rows"][0] == MASTER_COLUMNS
    assert len(VISIBLE_COLUMNS) == 16 and len(client.tabs) == 22
    metadata = client.metadata()
    assert [s["properties"]["title"] for s in metadata["sheets"] if not s["properties"]["hidden"]] == [
        MASTER_TAB,
        "LEADOS_DISCOVERY_RESULTS",
    ]
    assert client.tabs["Sheet1"]["rows"] == [["Keep these notes"], ["Existing data"]]
    assert client.tabs[MASTER_TAB]["properties"]["gridProperties"]["frozenRowCount"] == 1
    assert all(client.tabs[MASTER_TAB]["columns"][str(i)]["hiddenByUser"] for i in range(16, 20))
    assert len(client.tabs[MASTER_TAB]["conditional_formats"]) == len(COLORS)
    assert client.tabs[MASTER_TAB]["basic_filter"]["range"]["endColumnIndex"] == len(MASTER_COLUMNS)


def test_setup_repeat_does_not_change_technical_rows_or_duplicate_rules(overview):
    storage, client = overview
    before = {t: copy.deepcopy(client.tabs[t]["rows"]) for t in SCHEMAS}
    setup_master_workbook(client, storage.config)
    assert before == {t: client.tabs[t]["rows"] for t in SCHEMAS}
    assert len(client.tabs[MASTER_TAB]["conditional_formats"]) == len(COLORS)
    assert master_view_status(storage)["valid"]


async def test_current_dataset_has_one_row_for_every_opportunity_sorted(overview):
    storage, client = overview
    run = await populate(storage)
    rows = master_rows(client)
    assert run.metrics["opportunities_created"] == 44
    assert len(rows) == len({r["opportunity_id"] for r in rows}) == 44
    assert len({r["vertical"] for r in rows}) == 9
    assert len(storage.list(Company)) == 40
    assert [(-r["score"], r["trigger_date"]) for r in rows] == [
        (-r["score"], r["trigger_date"]) for r in MasterViewService(storage).build_rows()
    ]
    assert all(r["score"] == storage.get(Opportunity, r["opportunity_id"]).score for r in rows)
    assert all(r["score_status"] == storage.get(Opportunity, r["opportunity_id"]).score_band for r in rows)
    assert master_view_status(storage)["valid"]


async def test_repeat_discovery_keeps_master_ids_and_count(overview):
    storage, client = overview
    await populate(storage)
    ids = {r["opportunity_id"] for r in master_rows(client)}
    run = await populate(storage)
    assert run.metrics["opportunities_created"] == 0
    assert len(master_rows(client)) == 44
    assert ids == {r["opportunity_id"] for r in master_rows(client)}
    assert master_view_status(storage)["duplicates"] == 0


async def test_atlas_source_buyer_review_and_outreach_mapping(overview):
    storage, client = overview
    await populate(storage)
    atlas = next(
        r
        for r in master_rows(client)
        if r["company"] == "Atlas AI Systems" and r["vertical"] == "AI Governance"
    )
    assert atlas["score"] == 96 and atlas["score_status"] == "HOT"
    assert atlas["buyer"] == "General Counsel"
    assert atlas["review_status"] == "PENDING REVIEW"
    assert atlas["evidence_status"] == "VERIFIED"
    document = storage.get(SourceDocument, atlas["primary_source_id"])
    assert atlas["source"] == document.source_url
    draft = storage.first(OutreachDraft, opportunity_id=atlas["opportunity_id"])
    assert atlas["outreach_angle"] == draft.subjects[0]
    writes = [
        r
        for c in client.calls
        if c["method"] == "batch_update"
        for r in c["requests"]
        if "appendCells" in r and r["appendCells"]["sheetId"] == client.tabs[MASTER_TAB]["id"]
    ]
    source_cells = [
        row["values"][12]
        for write in writes
        for row in write["appendCells"]["rows"]
        if row["values"][16]["userEnteredValue"]["stringValue"] == atlas["opportunity_id"]
    ]
    assert source_cells[0]["userEnteredFormat"]["textFormat"]["link"]["uri"] == atlas["source"]
    assert all(
        "formulaValue" not in cell.get("userEnteredValue", {})
        for write in writes
        for row in write["appendCells"]["rows"]
        for cell in row["values"]
    )


async def test_unsupported_evidence_has_no_fabricated_source_or_hot_band(overview):
    storage, client = overview
    await populate(storage)
    for row in master_rows(client):
        opportunity = storage.get(Opportunity, row["opportunity_id"])
        if opportunity.audit_status != "VERIFIED":
            assert not row["source"] and not row["primary_source_id"]
            assert row["evidence_status"] in {"NEEDS RESEARCH", "REJECTED"}
            assert row["score_status"] != "HOT"
    weak = next(r for r in master_rows(client) if r["company"] == "Weak AI Rumors")
    assert weak["score"] > 80 and weak["score_status"] == "MONITOR"


async def test_source_confidence_then_publication_date_ranking(overview):
    storage, client = overview
    await populate(storage)
    opportunity = next(
        o
        for o in storage.list(Opportunity)
        if o.vertical_id == "ai_governance"
        and storage.get(Company, o.company_id).canonical_name == "Atlas AI Systems"
    )
    original = storage.get(
        SourceDocument, storage.first(OpportunityEvidence, opportunity_id=opportunity.id).document_id
    )
    documents = []
    with storage.transaction():
        for index, (confidence, published) in enumerate(
            [(0.99, date(2026, 10, 1)), (0.99, date(2026, 10, 5)), (1.0, date(2026, 9, 30))]
        ):
            snippet = original.snippet + f" Source ranking example {index}."
            url = f"https://ranking.example/event-{index}"
            document = SourceDocument(
                **{
                    **original.model_dump(exclude={"id", "created_at"}),
                    "source_url": url,
                    "url_hash": hashlib.sha256(url.encode()).hexdigest(),
                    "snippet": snippet,
                    "content_hash": hashlib.sha256(snippet.encode()).hexdigest(),
                    "confidence": confidence,
                    "published_date": published,
                }
            )
            storage.add(document)
            storage.add(OpportunityEvidence(opportunity_id=opportunity.id, document_id=document.id))
            documents.append(document)
    sync_master_view(storage)
    row = next(r for r in master_rows(client) if r["opportunity_id"] == opportunity.id)
    assert row["primary_source_id"] == documents[2].id
    with storage.transaction(refresh=True):
        storage.update(SourceDocument, documents[2].id, {"confidence": 0.99})
    sync_master_view(storage)
    assert (
        next(r for r in master_rows(client) if r["opportunity_id"] == opportunity.id)["primary_source_id"]
        == documents[1].id
    )


async def test_latest_review_wins_and_manual_opportunity_status_is_not_authoritative(overview):
    storage, client = overview
    await populate(storage)
    opportunity = storage.first(Opportunity, audit_status="VERIFIED")
    with storage.transaction():
        storage.update(Opportunity, opportunity.id, {"human_status": "APPROVED"})
    sync_master_view(storage)
    assert (
        next(r for r in master_rows(client) if r["opportunity_id"] == opportunity.id)["review_status"]
        == "PENDING REVIEW"
    )
    with storage.transaction():
        storage.add(
            HumanReview(
                opportunity_id=opportunity.id,
                reviewer="Test",
                decision="APPROVED",
                notes="",
                created_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        storage.add(
            HumanReview(
                opportunity_id=opportunity.id,
                reviewer="Test",
                decision="MONITOR",
                notes="",
                created_at=datetime.now(UTC),
            )
        )
    sync_master_view(storage)
    assert (
        next(r for r in master_rows(client) if r["opportunity_id"] == opportunity.id)["review_status"]
        == "MONITOR"
    )
    assert len(storage.list(HumanReview, opportunity_id=opportunity.id)) == 2


async def test_manual_master_review_edit_is_overwritten_without_domain_changes(overview):
    storage, client = overview
    await populate(storage)
    before = {t: copy.deepcopy(client.tabs[t]["rows"]) for t in SCHEMAS}
    client.tabs[MASTER_TAB]["rows"][1][14] = "APPROVED"
    assert not master_view_status(storage)["valid"]
    sync_master_view(storage)
    assert master_view_status(storage)["valid"]
    assert before == {t: client.tabs[t]["rows"] for t in SCHEMAS}


async def test_master_header_repair_preserves_reordered_cells_and_extra_notes(overview):
    storage, client = overview
    await populate(storage)
    rows = client.tabs[MASTER_TAB]["rows"]
    for row in rows:
        row.append(row.pop(0))
    rows[0].insert(0, "human_note")
    for row in rows[1:]:
        row.insert(0, "Preserve this note")
    assert not master_view_status(storage)["headers_valid"]
    setup_master_workbook(client, storage.config)
    assert rows[0] != client.tabs[MASTER_TAB]["rows"][0]  # atomic fake client stages requests
    assert client.tabs[MASTER_TAB]["rows"][0][: len(MASTER_COLUMNS)] == MASTER_COLUMNS
    assert all(
        row[len(MASTER_COLUMNS)] == "Preserve this note" for row in client.tabs[MASTER_TAB]["rows"][1:]
    )
    assert master_view_status(storage)["valid"]


def test_duplicate_master_header_stops_without_deleting_data(overview):
    storage, client = overview
    client.tabs[MASTER_TAB]["rows"][0].append("score")
    client.tabs[MASTER_TAB]["properties"]["gridProperties"]["columnCount"] = len(MASTER_COLUMNS) + 1
    before = copy.deepcopy(client.tabs)
    with pytest.raises(StorageError, match="master_view_duplicate_header"):
        setup_master_workbook(client, storage.config)
    assert before == client.tabs


async def test_manual_duplicate_row_detected_then_repaired_in_presentation_only(overview):
    storage, client = overview
    await populate(storage)
    client.tabs[MASTER_TAB]["rows"].append(copy.deepcopy(client.tabs[MASTER_TAB]["rows"][1]))
    before = {t: copy.deepcopy(client.tabs[t]["rows"]) for t in SCHEMAS}
    assert master_view_status(storage)["duplicates"] == 1
    sync_master_view(storage)
    assert len(master_rows(client)) == 44
    assert before == {t: client.tabs[t]["rows"] for t in SCHEMAS}
    assert master_view_status(storage)["valid"]


def test_debug_unhide_and_restore(overview):
    storage, client = overview
    config = storage.config.model_copy(update={"show_technical_sheets": True})
    setup_master_workbook(client, config)
    assert all(not s["properties"]["hidden"] for s in client.metadata()["sheets"])
    setup_master_workbook(client, storage.config)
    assert [
        s["properties"]["title"] for s in client.metadata()["sheets"] if not s["properties"]["hidden"]
    ] == [MASTER_TAB, "LEADOS_DISCOVERY_RESULTS"]


async def test_retries_after_committed_append_do_not_duplicate(overview):
    storage, client = overview
    await populate(storage)
    client.tabs[MASTER_TAB]["rows"].pop()
    client.fail_after_commit = True
    result = sync_master_view(storage)
    assert result["retries"] == 1 and len(master_rows(client)) == 44
    assert master_view_status(storage)["valid"]


async def test_projection_batches_current_dataset_and_noop_sync_writes_nothing(overview):
    storage, client = overview
    with storage.transaction():
        await Pipeline(storage, as_of=date(2026, 10, 6)).run()
    start = len([c for c in client.calls if c["method"] == "batch_update"])
    sync_master_view(storage)
    assert len([c for c in client.calls if c["method"] == "batch_update"]) - start == 1
    sync_master_view(storage)
    assert len([c for c in client.calls if c["method"] == "batch_update"]) - start == 1


def test_technical_bad_header_preflight_does_not_hide_or_change_data(overview):
    storage, client = overview
    client.tabs["OPPORTUNITIES"]["rows"][0].remove("total_score")
    before = copy.deepcopy(client.tabs)
    with pytest.raises(StorageError, match="missing_column"):
        setup_master_workbook(client, storage.config)
    assert before == client.tabs


async def test_application_api_auto_discovery_review_feedback_and_local_mode(db, monkeypatch):
    app.dependency_overrides.pop(get_db, None)
    monkeypatch.setattr("leados.storage.factory.runtime_storage", lambda: db)
    monkeypatch.setattr("leados.api.runtime_storage", lambda: db)
    with TestClient(app) as client:
        response = client.post("/pipeline/process", json={})
        assert response.status_code == 200 and response.headers["X-LeadOS-Master-View"] == "synced"
        assert client.get("/storage/master-view/status").json()["rows"] == 44
        opportunity = db.first(Opportunity, audit_status="VERIFIED")
        assert (
            client.post(
                f"/opportunities/{opportunity.id}/approve",
                json={"reviewer": "Master view test", "notes": "Synthetic acceptance"},
            ).status_code
            == 200
        )
        assert (
            next(r for r in MasterViewService(db).build_rows() if r["opportunity_id"] == opportunity.id)[
                "review_status"
            ]
            == "APPROVED"
        )
        assert writer_for(db).status(MasterViewService(db).build_rows())["rows"] == 44
        result = client.post(
            f"/opportunities/{opportunity.id}/feedback",
            json={"status": "Meeting", "buyer_role": "General Counsel", "notes": "Synthetic example"},
        )
        assert result.status_code == 200 and result.headers["X-LeadOS-Master-View"] == "synced"
        assert len(db.list(FeedbackEvent)) == 1
        assert client.get("/storage/master-view/status").json()["valid"]
        assert client.post("/pipeline/process", json={}).json()["metrics"]["opportunities_created"] == 0
        assert client.get("/storage/master-view/status").json()["rows"] == 44
        assert client.post(f"/opportunities/{opportunity.id}/send").status_code == 403


async def test_pending_projection_does_not_undo_business_commit_and_manual_sync_recovers(
    overview, monkeypatch
):
    storage, client = overview
    writer = writer_for(storage)
    original = writer.sync

    def fail(rows):
        raise StorageError("storage_timeout", retryable=True)

    monkeypatch.setattr(writer, "sync", fail)
    run = await populate(storage)
    assert run.metrics["opportunities_created"] == 44 and len(storage.list(Opportunity)) == 44
    status = master_view_status(storage)
    assert status["pending"] and status["last_error"]["code"] == "storage_timeout" and not status["valid"]
    monkeypatch.setattr(writer, "sync", original)
    sync_master_view(storage)
    assert master_view_status(storage)["valid"] and len(master_rows(client)) == 44
