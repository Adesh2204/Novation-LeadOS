"""Local JSON storage, with atomic replace and optional in-memory operation."""

import json
import os
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from leados.storage.base import StorageError, StorageProvider, normalize_run_history
from leados.storage.records import RECORD_TYPES, ProviderRun, Record


class MockStorageProvider(StorageProvider):
    name = "mock"

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else None
        self.provider_history: list[dict] = []
        super().__init__(self.path.with_suffix(".lock") if self.path else None)

    def _load(self):
        if not self.path or not self.path.exists():
            return self._records if self._loaded else {}
        try:
            payload = json.loads(self.path.read_text())
            self.provider_history = normalize_run_history(payload.get("provider_run_history", []))
            records = {
                name: {row["id"]: RECORD_TYPES[name].model_validate(row) for row in rows}
                for name, rows in payload["entities"].items()
            }
        except (ValueError, KeyError, ValidationError) as exc:
            raise StorageError("invalid_mock_file") from exc
        self.metrics["batch_reads"] += 1
        return records

    def _persist(self, changes: list[Record]):
        history = [*self.provider_history]
        existing = {row.get("snapshot_id"): row for row in history if row.get("snapshot_id")}
        for row in self._pending_run_history:
            if row["snapshot_id"] in existing:
                if existing[row["snapshot_id"]] != row:
                    raise StorageError("history_import_conflict")
            else:
                history.append(row)
                existing[row["snapshot_id"]] = row
        for r in changes:
            if isinstance(r, ProviderRun):
                data = r.model_dump(mode="json")
                if not any(
                    {k: v for k, v in row.items() if k != "snapshot_id"} == data
                    for row in self._pending_run_history
                ):
                    r.revision = (
                        max((row.get("revision", 0) for row in history if row["id"] == r.id), default=-1) + 1
                    )
                    data = r.model_dump(mode="json")
                    history.append({**data, "snapshot_id": "prs_" + str(uuid4())})
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".pending.json")
            payload = {
                "format_version": 1,
                "entities": {
                    name: [r.model_dump(mode="json") for r in rows.values()]
                    for name, rows in self._records.items()
                },
                "provider_run_history": history,
            }
            with temporary.open("w") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        self.provider_history = history
