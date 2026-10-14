"""Reproduce full master-view acceptance without accessing a live Google workbook."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from leados.api import app
from leados.config import settings
from leados.services.master_view import MasterViewService
from leados.storage.fake_google_client import MockGoogleSheetsClient
from leados.storage.google_sheets import GoogleSheetsStorageProvider
from leados.storage.master_view_schema import MASTER_TAB
from leados.storage.records import Company, CompanySignal
from leados.storage.setup import initialize_workbook
from leados.storage.workbook import SCHEMAS


def demo(workbook: Path) -> dict:
    with TemporaryDirectory(prefix="leados-master-acceptance-") as directory:
        google = MockGoogleSheetsClient()
        initialize_workbook(google)
        config = settings.model_copy(
            update={
                "storage_lock_path": str(Path(directory) / "writer.lock"),
                "storage_outbox_path": str(Path(directory) / "outbox.json"),
                "show_technical_sheets": False,
            }
        )
        storage = GoogleSheetsStorageProvider(google, config)
        with (
            patch("leados.storage.factory.runtime_storage", return_value=storage),
            patch("leados.api.runtime_storage", return_value=storage),
            TestClient(app) as api,
        ):
            first = api.post("/pipeline/process", json={})
            assert first.status_code == 200
            assert first.headers["X-LeadOS-Master-View"] == "synced"
            initial = MasterViewService(storage).build_rows()
            ids = {row["opportunity_id"] for row in initial}
            assert len(initial) == len(ids) == 44
            assert len({row["vertical"] for row in initial}) == 9
            assert len(storage.list(Company)) == 40
            assert len(storage.list(CompanySignal)) == 36
            atlas = next(
                row
                for row in initial
                if row["company"] == "Atlas AI Systems"
                and row["vertical"] == "AI Governance"
            )
            oid = atlas["opportunity_id"]
            approval = api.post(
                f"/opportunities/{oid}/approve",
                json={
                    "reviewer": "Master view acceptance",
                    "notes": "Synthetic fixture; no contact",
                },
            )
            assert approval.status_code == 200
            assert approval.headers["X-LeadOS-Master-View"] == "synced"
            second = api.post("/pipeline/process", json={})
            assert second.status_code == 200
            assert second.json()["metrics"]["opportunities_created"] == 0
            final = MasterViewService(storage).build_rows()
            assert len(final) == 44 and {r["opportunity_id"] for r in final} == ids
            approved = next(row for row in final if row["opportunity_id"] == oid)
            assert approved["review_status"] == "APPROVED"
            assert approved["source"] and approved["buyer"] == "General Counsel"
            weak = next(row for row in final if row["company"] == "Weak AI Rumors")
            assert weak["evidence_status"] == "NEEDS RESEARCH" and not weak["source"]
            status = api.get("/storage/master-view/status").json()
            assert status["valid"] and status["duplicates"] == 0
            technical = json.dumps(
                {tab: google.tabs[tab]["rows"] for tab in SCHEMAS}, sort_keys=True
            )
            assert api.post("/storage/master-view/sync").status_code == 200
            assert technical == json.dumps(
                {tab: google.tabs[tab]["rows"] for tab in SCHEMAS}, sort_keys=True
            )
            visible = [
                sheet["properties"]["title"]
                for sheet in google.metadata()["sheets"]
                if not sheet["properties"]["hidden"]
            ]
            assert visible == [MASTER_TAB]
            workbook.parent.mkdir(parents=True, exist_ok=True)
            workbook.write_text(
                json.dumps({"title": google.title, "tabs": google.tabs}, indent=2)
                + "\n"
            )
            return {
                "synthetic": True,
                "live_google_accessed": False,
                "first_run": first.json()["metrics"],
                "repeat_run": second.json()["metrics"],
                "companies": 40,
                "company_signals": 36,
                "opportunities": 44,
                "verticals": sorted({row["vertical"] for row in final}),
                "master_view": status,
                "visible_tabs": visible,
                "technical_rows_unchanged_by_manual_sync": True,
                "atlas": approved,
                "needs_research": weak,
            }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", default="data/master-view-demo-workbook.json")
    parser.add_argument("--report", default="docs/master_view_demo.json")
    args = parser.parse_args()
    result = demo(Path(args.workbook))
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2) + "\n")
    print(
        "Master view acceptance passed: 40 companies, 36 company signals, 44 rows, 9 verticals; repeat adds zero; approval auto-syncs."
    )


if __name__ == "__main__":
    main()
