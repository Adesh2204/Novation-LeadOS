import argparse
import json
from pathlib import Path

from leados.config import settings
from leados.services.master_view_sync import sync_master_view
from leados.storage.factory import build_storage
from leados.storage.transfer import import_data

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Import a portable LeadOS JSON export without overwriting history"
    )
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    storage = build_storage(settings)
    result = import_data(storage, json.loads(Path(args.input).read_text()))
    print(json.dumps({**result, "master_view": sync_master_view(storage)}))
