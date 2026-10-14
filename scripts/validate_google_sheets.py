"""Validate workbook headers/rows; optionally reconcile a pending write outbox."""

import argparse
import json
from pathlib import Path

from leados.config import settings
from leados.services.master_view_sync import master_view_status
from leados.storage.base import StorageError
from leados.storage.fake_google_client import MockGoogleSheetsClient
from leados.storage.google_client import GoogleSheetsClient
from leados.storage.google_sheets import GoogleSheetsStorageProvider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--input", default="data/mock-workbook.json")
    parser.add_argument("--show-technical-sheets", action="store_true")
    parser.add_argument(
        "--recover",
        action="store_true",
        help="Reconcile and retry only the persisted pending write",
    )
    args = parser.parse_args()
    client = MockGoogleSheetsClient() if args.mock else GoogleSheetsClient(settings)
    if args.mock:
        with open(args.input) as handle:
            payload = json.load(handle)
        client.tabs, client.title = payload["tabs"], payload["title"]
    config = (
        settings.model_copy(update={"show_technical_sheets": True})
        if args.show_technical_sheets
        else settings
    )
    if args.mock:
        path = Path(args.input)
        config = config.model_copy(
            update={
                "storage_lock_path": str(path.with_suffix(".lock")),
                "storage_outbox_path": str(path.with_suffix(".outbox.json")),
            }
        )
    provider = GoogleSheetsStorageProvider(client, config)
    try:
        if args.recover:
            print(json.dumps(provider.recover()))
        with provider.transaction(refresh=True):
            result = provider.health()
        result["master_view"] = master_view_status(provider)
        print(json.dumps(result))
        if not result["rows_valid"] or not result["master_view"]["valid"]:
            raise SystemExit(1)
    except StorageError as exc:
        raise SystemExit(f"{exc.code}: {exc.detail}") from None
    finally:
        client.close()


if __name__ == "__main__":
    main()
