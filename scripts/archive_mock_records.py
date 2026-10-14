"""Dry run by default. Applying retains canonical records and their entire reference graph."""

import argparse
import json
from pathlib import Path

from leados.config import settings
from leados.services.provenance import apply_classification, classify
from leados.storage.factory import build_storage
from leados.storage.transfer import export_data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", default="data/archives/production-repair-20261009")
    args = parser.parse_args()
    directory = Path(args.output)
    directory.mkdir(parents=True, exist_ok=True)
    storage = build_storage(settings)
    with storage.transaction(refresh=True):
        report = classify(storage)
    (directory / "classification-dry-run.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "records"}))
    if args.apply:
        # Another fresh backup precedes all canonical mutations and schema additions.
        export_data(storage, directory / "before-apply")
        if settings.leados_storage == "google_sheets":
            from leados.storage.setup import initialize_workbook

            initialize_workbook(storage.client, max_rows=settings.sheets_max_rows)
        with storage.transaction(refresh=True):
            current = classify(storage)
            if current["records"] != report["records"]:
                raise RuntimeError(
                    "Origin inventory changed; repeat dry run before applying"
                )
            apply_classification(storage, report)
        export_data(storage, directory / "after-apply")
        print(
            "Archived logically; no business records deleted. Review history and source UUIDs retained."
        )


if __name__ == "__main__":
    main()
