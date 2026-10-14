"""One-time SQL-to-StorageProvider migration; core runtime never imports SQL."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from leados.config import settings
from leados.storage.factory import build_storage
from leados.storage.records import RECORD_TYPES
from leados.storage.transfer import import_data


def migrate_snapshot(data):
    signal_ids = {
        row["id"]: "sig_" + str(uuid5(NAMESPACE_URL, "leados:signal:" + row["id"]))
        for row in data.get("Signal", [])
    }
    result = {}
    for name, rows in data.items():
        result[name] = []
        for raw in rows:
            row = dict(raw)
            if name == "Signal":
                row.update(id=signal_ids[row["id"]], code=row["id"])
            elif name == "CompanySignal":
                row.update(
                    signal_key=row["signal_id"], signal_id=signal_ids[row["signal_id"]]
                )
            for field, info in RECORD_TYPES[name].model_fields.items():
                if field not in row:
                    continue
                value = row[field]
                if value and "datetime" in str(info.annotation):
                    dt = (
                        value
                        if isinstance(value, datetime)
                        else datetime.fromisoformat(value)
                    )
                    row[field] = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
            # New timestamps use creation time so repeated migration stays deterministic.
            if name in {"Company", "SourceDocument", "CompanySignal"}:
                row["last_seen_at"] = row.get("updated_at", row.get("created_at"))
            result[name].append(
                RECORD_TYPES[name].model_validate(row).model_dump(mode="json")
            )
    from leados.storage.base import fingerprint

    company_signals = {s["id"]: s for s in result.get("CompanySignal", [])}
    for o in result.get("Opportunity", []):
        signal = company_signals[o["company_signal_id"]]
        o["opportunity_fingerprint"] = fingerprint(
            o["company_id"], o["vertical_id"], signal["signal_id"], signal["event_key"]
        )
    return {"format_version": 1, "entities": result}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", help="Previously exported legacy JSON snapshot")
    args = parser.parse_args()
    if args.snapshot:
        data = json.loads(Path(args.snapshot).read_text())
    else:
        from leados import models  # noqa: F401
        from leados.db import Base, SessionLocal
        from sqlalchemy import select

        with SessionLocal() as session:
            data = {
                m.class_.__name__: [
                    {c.name: getattr(row, c.name) for c in m.columns}
                    for row in session.scalars(select(m.class_))
                ]
                for m in Base.registry.mappers
            }
    from leados.services.master_view_sync import sync_master_view

    storage = build_storage(settings)
    print(
        json.dumps(
            {
                **import_data(storage, migrate_snapshot(data)),
                "master_view": sync_master_view(storage),
            }
        )
    )
