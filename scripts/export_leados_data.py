import argparse
import json
from pathlib import Path

from leados.config import settings
from leados.storage.factory import build_storage
from leados.storage.transfer import export_data

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Export all LeadOS entities as JSON and CSV"
    )
    parser.add_argument("--output", default="data/export")
    args = parser.parse_args()
    print(json.dumps(export_data(build_storage(settings), Path(args.output))))
