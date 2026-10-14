"""Initialize the chosen existing spreadsheet; never delete existing rows."""

import argparse
import json
from pathlib import Path

from leados.config import settings
from leados.services.master_view_setup import setup_master_workbook
from leados.storage.base import StorageError
from leados.storage.fake_google_client import MockGoogleSheetsClient
from leados.storage.google_client import GoogleSheetsClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Create a local fake workbook without Google access",
    )
    parser.add_argument("--output", default="data/mock-workbook.json")
    parser.add_argument(
        "--show-technical-sheets",
        action="store_true",
        help="Debug: unhide the technical tabs",
    )
    args = parser.parse_args()
    client = MockGoogleSheetsClient() if args.mock else GoogleSheetsClient(settings)
    output = Path(args.output)
    if args.mock and output.exists():
        payload = json.loads(output.read_text())
        client.tabs = payload["tabs"]
        client.title = payload["title"]
    try:
        config = (
            settings.model_copy(update={"show_technical_sheets": True})
            if args.show_technical_sheets
            else settings
        )
        if args.mock:
            config = config.model_copy(
                update={
                    "storage_lock_path": str(output.with_suffix(".lock")),
                    "storage_outbox_path": str(output.with_suffix(".outbox.json")),
                }
            )
        result = setup_master_workbook(client, config)
        if args.mock:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps({"title": client.title, "tabs": client.tabs}, indent=2)
            )
        print(json.dumps(result))
    except StorageError as exc:
        raise SystemExit(f"{exc.code}: {exc.detail}") from None
    finally:
        client.close()


if __name__ == "__main__":
    main()
