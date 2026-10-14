"""Portable data transfer: IDs, typed fields and immutable history survive migration."""

import csv
import json
from pathlib import Path

from leados.storage.base import StorageError
from leados.storage.records import RECORD_TYPES, AuditLog

ORDER = [
    "Vertical",
    "Service",
    "Company",
    "CompanyAlias",
    "Source",
    "SourceDocument",
    "Signal",
    "CompanySignal",
    "Opportunity",
    "OpportunityEvidence",
    "ScoreComponent",
    "DecisionMakerRole",
    "OutreachDraft",
    "HumanReview",
    "HumanReviewTask",
    "FeedbackEvent",
    "Suppression",
    "ContactEvent",
    "ProviderRun",
    "AuditLog",
    "SystemConfig",
]


def export_data(storage, directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    with storage.transaction(refresh=True):
        entities = {
            name: [
                r.model_dump(mode="json")
                for r in storage.list(RECORD_TYPES[name])
                if not (name == "SystemConfig" and r.key == "LAST_COMMIT_ID")
            ]
            for name in ORDER
        }
        payload = {
            "format_version": 1,
            "entities": entities,
            "provider_run_history": getattr(storage, "provider_history", []),
        }
        (directory / "leados.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        for name, rows in entities.items():
            with (directory / f"{name}.csv").open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(RECORD_TYPES[name].model_fields))
                writer.writeheader()
                writer.writerows(
                    {
                        k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                        for k, v in row.items()
                    }
                    for row in rows
                )
        storage.save_audit_event(
            AuditLog(
                module="storage_transfer", action="export", output_ref=str(directory.resolve()), success=True
            )
        )
    return {
        "directory": str(directory.resolve()),
        "counts": {k: len(v) for k, v in entities.items()},
        "format_version": 1,
    }


def import_data(storage, payload: dict):
    if payload.get("format_version") != 1 or set(payload.get("entities", {})) - set(RECORD_TYPES):
        raise StorageError("invalid_import_format")
    # Validate every payload before touching the target provider.
    records = {
        name: [RECORD_TYPES[name].model_validate(row) for row in payload["entities"].get(name, [])]
        for name in ORDER
    }
    counts = {"created": 0, "unchanged": 0}
    with storage.transaction(refresh=True):
        for name in ORDER:
            for record in records[name]:
                existing = storage.get(type(record), record.id)
                if existing:
                    left = existing.model_dump(mode="json")
                    right = record.model_dump(mode="json")
                    if name in {"Vertical", "Service", "Signal"}:
                        left.pop("created_at", None)
                        right.pop("created_at", None)
                    if left != right:
                        raise StorageError("import_conflict", name)
                    counts["unchanged"] += 1
                else:
                    storage.add(record)
                    counts["created"] += 1
        storage.import_run_history(payload.get("provider_run_history", []))
        storage.save_audit_event(AuditLog(module="storage_transfer", action="import", success=True))
    return counts
