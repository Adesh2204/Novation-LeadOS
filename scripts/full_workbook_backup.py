"""Read-only snapshot including projection cells and unowned columns."""

import json
from pathlib import Path

from leados.config import settings
from leados.storage.google_client import GoogleSheetsClient
from leados.storage.workbook import column_name

client = GoogleSheetsClient(settings)
metadata = client.metadata()
properties = [s["properties"] for s in metadata["sheets"]]
ranges = [
    f"'{p['title']}'!A1:{column_name(p['gridProperties']['columnCount'])}{p['gridProperties']['rowCount']}"
    for p in properties
]
values = client.batch_read(ranges)
path = Path(
    "data/archives/production-repair-20261009/workbook-before-presentation-repair.json"
)
path.write_text(
    json.dumps(
        {
            "metadata": metadata,
            "tabs": dict(zip([p["title"] for p in properties], values, strict=True)),
        },
        indent=2,
    )
)
print(json.dumps({"backup": str(path), "tabs": len(values)}))
