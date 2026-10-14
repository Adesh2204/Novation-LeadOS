"""Sheets operational storage: UUID lookup, batching, outbox and guarded writes."""

import json
import os
import time
from collections import defaultdict
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import ValidationError

from leados.config import Settings
from leados.storage.base import IMMUTABLE, UNIQUE, StorageError, StorageProvider
from leados.storage.records import RECORD_TYPES, AuditLog, ProviderRun, Record, SystemConfig
from leados.storage.workbook import ENTITY_TABS, SCHEMAS, WORKBOOK_NAME, cell, column_name


def cells(values: list) -> dict:
    return {
        "values": [
            {
                "userEnteredValue": {
                    "boolValue"
                    if isinstance(v, bool)
                    else "numberValue"
                    if isinstance(v, (int, float))
                    else "stringValue": v
                }
            }
            for v in values
        ]
    }


class GoogleSheetsStorageProvider(StorageProvider):
    name = "google_sheets"

    def __init__(self, client, config: Settings | None = None):
        self.client = client
        self.config = config or Settings()
        self.outbox = Path(self.config.storage_outbox_path)
        self._metadata: dict | None = None
        self._sheet_ids: dict = {}
        self._rows: dict = {}
        self._headers: dict = {}
        self._invalid_pending: list[dict] = []
        self.provider_history: list[dict] = []
        self._reported_validation: set[str] = set()
        self._blocked_company_keys: set[str] = set()
        self._blocked_unique: dict = {}
        super().__init__(Path(self.config.storage_lock_path))

    def _read(self, *, metadata=False):
        if self._metadata is None or metadata:
            self._metadata = self.client.metadata()
            if self._metadata["properties"]["title"] != WORKBOOK_NAME:
                raise StorageError("wrong_workbook_title", f"Expected {WORKBOOK_NAME}")
            self._sheet_ids = {
                s["properties"]["title"]: s["properties"]["sheetId"] for s in self._metadata["sheets"]
            }
        assert self._metadata is not None
        for tab in SCHEMAS:
            if tab not in self._sheet_ids:
                raise StorageError("missing_sheet", f"{tab} sheet missing.")
        properties = {s["properties"]["title"]: s["properties"] for s in self._metadata["sheets"]}
        raw = self.client.batch_read(
            [
                f"'{tab}'!A1:{column_name(properties[tab].get('gridProperties', {}).get('columnCount', len(SCHEMAS[tab].headers)))}{min(properties[tab].get('gridProperties', {}).get('rowCount', self.config.sheets_max_rows + 2), self.config.sheets_max_rows + 2)}"
                for tab in SCHEMAS
            ]
        )
        self.metrics["batch_reads"] += 1
        if len(raw) != len(SCHEMAS):
            raise StorageError("incomplete_batch_read")
        rows = dict(zip(SCHEMAS, raw, strict=True))
        for tab, values in rows.items():
            if len(values) > self.config.sheets_max_rows + 1:
                raise StorageError("row_limit_exceeded", tab)
            headers = values[0] if values else []
            SCHEMAS[tab].validate_headers(headers)
        return rows

    def _decode(self, rows):
        records: dict = {}
        errors = []
        self.provider_history = []
        self.quarantined_ids = set()
        self._blocked_company_keys = set()
        self._blocked_unique = {}
        for tab, values in rows.items():
            schema = SCHEMAS[tab]
            extras = set(values[0]) - set(schema.headers)
            if extras:
                errors.append({"tab": tab, "code": "unexpected_column", "count": len(extras)})
            seen: dict = {}
            for number, row in enumerate(values[1:], 2):
                if not any(v != "" for v in row):
                    continue
                id_column = (
                    "snapshot_id" if schema.entity == "ProviderRun" else schema.aliases.get("id", "id")
                )
                idx = values[0].index(id_column)
                rid = str(row[idx]) if idx < len(row) else ""
                if rid in seen:
                    self._block_raw_unique(schema, values[0], row)
                    errors.append({"tab": tab, "row": number, "code": "duplicate_record"})
                    self.quarantined_ids.add(rid)
                    records.get(schema.entity, {}).pop(rid, None)
                    continue
                seen[rid] = number
                try:
                    record = schema.decode(values[0], row)
                    if schema.entity == "ProviderRun":
                        self.provider_history.append({**record.model_dump(mode="json"), "snapshot_id": rid})
                        prior = records.get(schema.entity, {}).get(record.id)
                        if prior and prior.revision >= record.revision:
                            continue
                    records.setdefault(schema.entity, {})[record.id] = record
                except (ValidationError, StorageError, ValueError, TypeError) as exc:
                    self._block_raw_unique(schema, values[0], row)
                    self.quarantined_ids.add(rid)
                    if schema.entity == "Company" and "identity_key" in values[0]:
                        key_position = values[0].index("identity_key")
                        if key_position < len(row):
                            self._blocked_company_keys.add(str(row[key_position]))
                    errors.append(
                        {
                            "tab": tab,
                            "row": number,
                            "code": exc.code if isinstance(exc, StorageError) else "invalid_row",
                        }
                    )
        self.validation_errors = errors[:100]
        self._invalid_pending = errors[:100]
        return records

    def _block_raw_unique(self, schema, headers, row):
        values = dict(zip(headers, row, strict=False))
        for fields in UNIQUE.get(schema.model, []):
            key = tuple(str(values.get(schema.aliases.get(f, f), "")) for f in fields)
            if all(key):
                self._blocked_unique.setdefault((schema.entity, fields), set()).add(key)

    def add(self, record):
        self._ensure()
        if type(record).__name__ == "Company" and record.identity_key in self._blocked_company_keys:
            raise StorageError("quarantined_identity", "COMPANIES")
        self._validate_record(record)
        for fields in UNIQUE.get(type(record), []):
            key = tuple(str(getattr(record, f)) for f in fields)
            if key in self._blocked_unique.get((type(record).__name__, fields), set()):
                raise StorageError("quarantined_unique_key", type(record).__name__)
        return super().add(record)

    def _validate_loaded(self):
        from leados.engine import score_band
        from leados.knowledge import knowledge
        from leados.storage.records import Opportunity, ScoreComponent

        for model, constraints in UNIQUE.items():
            for fields in constraints:
                seen: dict = {}
                for record in list(self._records.get(model.__name__, {}).values()):
                    key = tuple(getattr(record, f) for f in fields)
                    if any(v in {None, ""} for v in key):
                        continue
                    if key in seen:
                        for rid in [record.id, seen[key]]:
                            self.quarantined_ids.add(rid)
                            self._records[model.__name__].pop(rid, None)
                        self.validation_errors.append(
                            {"tab": ENTITY_TABS.get(model.__name__), "code": "duplicate_unique_key"}
                        )
                    else:
                        seen[key] = record.id
        # Quarantine malformed records and their dependants; never delete their Sheet rows.
        for _ in range(20):
            removed = False
            for name, records in self._records.items():
                for record in list(records.values()):
                    try:
                        self._validate_record(record)
                        if isinstance(record, Opportunity):
                            parts = self.list(ScoreComponent, opportunity_id=record.id)
                            if (
                                {p.name: p.maximum for p in parts} != knowledge.scoring["components"]
                                or sum(p.points for p in parts) != record.score
                                or any(not 0 <= p.points <= p.maximum for p in parts)
                            ):
                                raise StorageError("invalid_score_components")
                            expected = (
                                score_band(record.score, knowledge.scoring)
                                if record.audit_status == "VERIFIED"
                                else "IGNORE"
                                if record.audit_status == "REJECTED"
                                else "MONITOR"
                            )
                            if record.score_band != expected:
                                raise StorageError("invalid_score_band")
                    except (StorageError, ValidationError, ValueError) as exc:
                        for fields in UNIQUE.get(type(record), []):
                            self._blocked_unique.setdefault((name, fields), set()).add(
                                tuple(str(getattr(record, f)) for f in fields)
                            )
                        records.pop(record.id, None)
                        self.quarantined_ids.add(record.id)
                        self.validation_errors.append(
                            {
                                "tab": ENTITY_TABS.get(name),
                                "code": exc.code if isinstance(exc, StorageError) else "invalid_row",
                            }
                        )
                        self._indexes.clear()
                        removed = True
            if not removed:
                break
        for error in self.validation_errors:
            signature = json.dumps(error, sort_keys=True)
            if signature not in self._reported_validation:
                self._reported_validation.add(signature)
                audit = AuditLog(
                    module="storage_validation",
                    action="quarantine_or_warn",
                    entity_type=error.get("tab") or "",
                    success=False,
                    error=error["code"],
                )
                self._records.setdefault("AuditLog", {})[audit.id] = audit

    def _load(self):
        self._rows = self._read(metadata=True)
        self._headers = {tab: rows[0] for tab, rows in self._rows.items()}
        return self._decode(self._rows)

    def _changes_request(self, changes, rows, commit_id):
        requests = []
        groups = defaultdict(list)
        for record in changes:
            tab = ENTITY_TABS.get(type(record).__name__)
            if tab:
                groups[tab].append(record)
        for tab, records in groups.items():
            schema = SCHEMAS[tab]
            headers = rows[tab][0]
            current: dict = {}
            idcol = headers.index(schema.aliases.get("id", "id"))
            for number, row in enumerate(rows[tab][1:], 1):
                if idcol < len(row):
                    current.setdefault(str(row[idcol]), []).append((number, row))
            appends = []
            for record in records:
                if isinstance(record, ProviderRun) and any(
                    {k: v for k, v in item.items() if k != "snapshot_id"} == record.model_dump(mode="json")
                    for item in self._pending_run_history
                ):
                    continue
                matches = current.get(record.id, [])
                baseline = self._baseline.get(type(record).__name__, {}).get(record.id)
                if isinstance(record, ProviderRun):
                    revisions = [schema.decode(headers, row).revision for _, row in matches]
                    record.revision = max(revisions, default=-1) + 1
                    snapshot_id = "prs_" + str(uuid5(NAMESPACE_URL, commit_id + record.id))
                else:
                    snapshot_id = ""
                    if len(matches) > 1:
                        raise StorageError("duplicate_record", tab)
                    if matches:
                        try:
                            actual = schema.decode(headers, matches[0][1]).model_dump(mode="json")
                        except Exception as exc:
                            raise StorageError("concurrent_edit_conflict", tab) from exc
                        if baseline is None or actual != baseline:
                            raise StorageError("concurrent_edit_conflict", tab)
                        if type(record) in IMMUTABLE:
                            raise StorageError("immutable_history", tab)
                    elif baseline is not None:
                        raise StorageError("record_deleted", tab)
                encoded = schema.encode(record, self, snapshot_id=snapshot_id)
                values = [
                    (v[:48000] + "... [TRUNCATED]") if isinstance(v, str) and len(v) > 48000 else v
                    for v in (cell(encoded.get(h, "")) for h in headers)
                ]
                if matches and not isinstance(record, ProviderRun):
                    # Write only owned columns, preserving additional human columns/formulas.
                    position = matches[0][0]
                    start = 0
                    while start < len(headers):
                        if headers[start] not in schema.headers:
                            start += 1
                            continue
                        end = start + 1
                        while end < len(headers) and headers[end] in schema.headers:
                            end += 1
                        requests.append(
                            {
                                "updateCells": {
                                    "start": {
                                        "sheetId": self._sheet_ids[tab],
                                        "rowIndex": position,
                                        "columnIndex": start,
                                    },
                                    "rows": [cells(values[start:end])],
                                    "fields": "userEnteredValue",
                                }
                            }
                        )
                        start = end
                else:
                    appends.append(cells(values))
            if appends:
                if len(rows[tab]) - 1 + len(appends) > self.config.sheets_max_rows:
                    raise StorageError("row_limit_exceeded", tab)
                requests.append(
                    {
                        "appendCells": {
                            "sheetId": self._sheet_ids[tab],
                            "rows": appends,
                            "fields": "userEnteredValue",
                        }
                    }
                )
        if self._pending_run_history:
            schema = SCHEMAS["PROVIDER_RUNS"]
            headers = rows["PROVIDER_RUNS"][0]
            position = headers.index("snapshot_id")
            existing_history = {
                str(row[position]): row for row in rows["PROVIDER_RUNS"][1:] if len(row) > position
            }
            history_rows = []
            for item in self._pending_run_history:
                data = {k: v for k, v in item.items() if k != "snapshot_id"}
                if item["snapshot_id"] in existing_history:
                    if (
                        schema.decode(headers, existing_history[item["snapshot_id"]]).model_dump(mode="json")
                        != data
                    ):
                        raise StorageError("history_import_conflict")
                    continue
                record = ProviderRun.model_validate(data)
                encoded = schema.encode(record, self, snapshot_id=item["snapshot_id"])
                history_rows.append(cells([cell(encoded.get(h, "")) for h in headers]))
            if history_rows:
                if len(rows["PROVIDER_RUNS"]) - 1 + len(history_rows) > self.config.sheets_max_rows:
                    raise StorageError("row_limit_exceeded", "PROVIDER_RUNS")
                requests.append(
                    {
                        "appendCells": {
                            "sheetId": self._sheet_ids["PROVIDER_RUNS"],
                            "rows": history_rows,
                            "fields": "userEnteredValue",
                        }
                    }
                )
        marker_schema = SCHEMAS["SYSTEM_CONFIG"]
        headers = rows["SYSTEM_CONFIG"][0]
        key_position = headers.index("key")
        marker = SystemConfig(
            id="cfg_" + str(uuid5(NAMESPACE_URL, "leados:last_commit")), key="LAST_COMMIT_ID", value=commit_id
        )
        existing = next(
            (
                (number, row)
                for number, row in enumerate(rows["SYSTEM_CONFIG"][1:], 1)
                if key_position < len(row) and row[key_position] == "LAST_COMMIT_ID"
            ),
            None,
        )
        values = [cell(marker_schema.encode(marker, self).get(h, "")) for h in headers]
        if existing:
            requests.append(
                {
                    "updateCells": {
                        "start": {
                            "sheetId": self._sheet_ids["SYSTEM_CONFIG"],
                            "rowIndex": existing[0],
                            "columnIndex": 0,
                        },
                        "rows": [cells(values)],
                        "fields": "userEnteredValue",
                    }
                }
            )
        else:
            requests.append(
                {
                    "appendCells": {
                        "sheetId": self._sheet_ids["SYSTEM_CONFIG"],
                        "rows": [cells(values)],
                        "fields": "userEnteredValue",
                    }
                }
            )
        if len(json.dumps(requests).encode()) > 1800000:
            raise StorageError("batch_payload_too_large", "Use smaller company runs")
        return requests

    def _has_commit(self, rows, commit_id):
        headers = rows["SYSTEM_CONFIG"][0]
        keypos, valpos = headers.index("key"), headers.index("value")
        return any(
            len(row) > max(keypos, valpos) and row[keypos] == "LAST_COMMIT_ID" and row[valpos] == commit_id
            for row in rows["SYSTEM_CONFIG"][1:]
        )

    def _persist(self, changes: list[Record], *, recovery=None):
        changes = [r for r in changes if type(r).__name__ in ENTITY_TABS]
        if not changes and not self._pending_run_history:
            return
        if self.outbox.exists() and recovery is None:
            raise StorageError("pending_write_recovery_required")
        commit_id = recovery or str(uuid4())
        payload = {
            "commit_id": commit_id,
            "changes": [{"entity": type(r).__name__, "record": r.model_dump(mode="json")} for r in changes],
            "baseline": self._baseline,
            "run_history": self._pending_run_history,
        }
        self.outbox.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.outbox.with_suffix(".pending")
        with temporary.open("w") as handle:
            json.dump(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.outbox)
        for attempt in range(self.config.sheets_max_attempts):
            try:
                rows = self._read()
                if self._has_commit(rows, commit_id):
                    self.outbox.unlink(missing_ok=True)
                    return
                requests = self._changes_request(changes, rows, commit_id)
                self.client.batch_update(requests)
                self.outbox.unlink(missing_ok=True)
                return
            except StorageError as exc:
                if not exc.retryable:
                    # Known pre-write validation conflicts are safe to discard/re-read.
                    if exc.code in {
                        "concurrent_edit_conflict",
                        "duplicate_record",
                        "record_deleted",
                        "batch_payload_too_large",
                        "cell_payload_too_large",
                        "row_limit_exceeded",
                        "history_import_conflict",
                    }:
                        self.outbox.unlink(missing_ok=True)
                    raise
                if attempt + 1 == self.config.sheets_max_attempts:
                    raise
                self.metrics["retries"] += 1
                time.sleep(max(exc.retry_after, min(0.25 * 2**attempt, 5)))

    def recover(self):
        """Replay a known outbox after UUID reconciliation; never blindly append twice."""
        if not self.outbox.exists():
            return {"recovered": False, "pending": False}
        with self.transaction(refresh=True):
            payload = json.loads(self.outbox.read_text())
            rows = self._read(metadata=True)
            if self._has_commit(rows, payload["commit_id"]):
                self.outbox.unlink()
                self._loaded = False
                return {"recovered": True, "pending": False}
            self._ensure(refresh=True)
            self._baseline = payload["baseline"]
            changes = [
                RECORD_TYPES[item["entity"]].model_validate(item["record"]) for item in payload["changes"]
            ]
            self._pending_run_history = payload.get("run_history", [])
            for record in changes:
                self._records.setdefault(type(record).__name__, {})[record.id] = record
            self._persist(changes, recovery=payload["commit_id"])
            self._baseline = self.snapshot()
            self._pending_run_history = []
            return {"recovered": True, "pending": False}

    def health(self):
        result = super().health()
        result.update(
            pending_write=self.outbox.exists(),
            client_metrics=dict(self.client.metrics),
            max_rows_per_tab=self.config.sheets_max_rows,
        )
        return result
