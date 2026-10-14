"""Presentation-only persistence/layout; accepts flat rows, never joins domain records."""

import json
import os
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from leados.config import Settings
from leados.storage.base import StorageError
from leados.storage.google_sheets import cells
from leados.storage.master_view_schema import MASTER_COLUMNS, MASTER_TAB
from leados.storage.workbook import SCHEMAS, WORKBOOK_NAME, column_name

OWNED_WIDTH = len(MASTER_COLUMNS)
ROW_ID_INDEX = MASTER_COLUMNS.index("row_id")


def row_identity(row):
    return row.get("row_id") or row["opportunity_id"]


SYNC_KEY = "LEADOS_MASTER_VIEW_LAST_SYNCED_AT"
META_FIELDS = "spreadsheetId,properties(title),sheets(properties,conditionalFormats,developerMetadata,data(startColumn,columnMetadata(hiddenByUser)))"
WIDTHS = [180, 120, 100, 260, 110, 170, 210, 320, 70, 90, 90, 120, 200, 160, 120, 320]
COLORS = [
    (9, "HOT", (0.80, 0.93, 0.82)),
    (9, "STRONG", (1, 0.89, 0.72)),
    (9, "MONITOR", (1, 0.96, 0.72)),
    (9, "IGNORE", (0.92, 0.92, 0.92)),
    (11, "NEEDS RESEARCH", (1, 0.86, 0.86)),
    (14, "APPROVED", (0.80, 0.93, 0.82)),
    (14, "REJECTED", (1, 0.80, 0.80)),
    (14, "NEEDS RESEARCH", (1, 0.86, 0.86)),
    (14, "PENDING REVIEW", (0.95, 0.95, 0.95)),
]


def utc_now():
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".pending.json")
    with temporary.open("w") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def flat_values(row: dict) -> list:
    return [row.get(name, "") for name in MASTER_COLUMNS]


class JsonMasterViewWriter:
    """Local presentation artifact for credential-free JSON mode."""

    def __init__(self, path: Path | None):
        self.path = path
        self.payload: dict = {}

    def sync(self, rows: list[dict]):
        if self.path and self.path.exists():
            self.payload = json.loads(self.path.read_text())
        if self.payload.get("rows") != rows or not self.payload:
            self.payload = {
                "tab": MASTER_TAB,
                "columns": MASTER_COLUMNS,
                "rows": rows,
                "last_synced_at": utc_now(),
            }
            if self.path:
                atomic_json(self.path, self.payload)
        return self.status(rows)

    def status(self, expected: list[dict]):
        if self.path and self.path.exists():
            self.payload = json.loads(self.path.read_text())
        rows = self.payload.get("rows", [])
        duplicates = sum(n - 1 for n in Counter(row_identity(r) for r in rows).values())
        return {
            "provider": "mock",
            "rows": len(rows),
            "expected_rows": len(expected),
            "last_synced_at": self.payload.get("last_synced_at"),
            "duplicates": duplicates,
            "technical_sheets_hidden": None,
            "master_view_visible": None,
            "headers_valid": self.payload.get("columns") == MASTER_COLUMNS,
            "rows_match": rows == expected,
            "valid": rows == expected and not duplicates and bool(self.payload),
            "presentation": "local JSON; no Google workbook modified",
        }


class SheetsMasterViewWriter:
    def __init__(self, client, config: Settings):
        self.client, self.config = client, config

    def metadata(self):
        # A ranges filter also removes other sheets from Google's response. Read
        # all sheet properties plus column visibility, without any row/cell data.
        metadata = self.client.metadata(fields=META_FIELDS)
        if metadata["properties"]["title"] != WORKBOOK_NAME:
            raise StorageError("wrong_workbook_title", WORKBOOK_NAME)
        return metadata

    def _read(self):
        metadata = self.metadata()
        sheets = {s["properties"]["title"]: s for s in metadata["sheets"]}
        for tab in SCHEMAS:
            if tab not in sheets:
                raise StorageError("missing_sheet", tab)
        master = sheets.get(MASTER_TAB)
        raw = []
        if master:
            props = master["properties"]
            width = props["gridProperties"]["columnCount"]
            raw = self.client.batch_read(
                [
                    f"'{MASTER_TAB}'!A1:{column_name(width)}{min(props['gridProperties']['rowCount'], self.config.sheets_max_rows + 2)}"
                ]
            )[0]
            if len(raw) > self.config.sheets_max_rows + 1:
                raise StorageError("master_view_row_limit")
        return metadata, sheets, master, raw

    def initialize(self):
        metadata, sheets, master, raw = self._read()
        headers = list(raw[0]) if raw else []
        if len(headers) != len(set(headers)):
            raise StorageError("master_view_duplicate_header")
        if not headers and len(raw) > 1 and any(any(r) for r in raw[1:]):
            raise StorageError("master_view_missing_header", "Existing presentation data has no header")
        requests: list[dict] = []
        created = master is None
        height = self.config.sheets_max_rows + 2
        if created:
            used = {s["properties"]["sheetId"] for s in metadata["sheets"]}
            sid = next(i for i in range(100, 10000) if i not in used)
            requests.append(
                {
                    "addSheet": {
                        "properties": {
                            "sheetId": sid,
                            "title": MASTER_TAB,
                            "hidden": False,
                            "gridProperties": {"rowCount": height, "columnCount": OWNED_WIDTH},
                        }
                    }
                }
            )
        else:
            sid = master["properties"]["sheetId"]
            height = max(height, master["properties"]["gridProperties"]["rowCount"])
        missing = [column for column in MASTER_COLUMNS if column not in headers]
        width = max(
            OWNED_WIDTH,
            len(headers) + len(missing),
            master["properties"]["gridProperties"]["columnCount"] if master else OWNED_WIDTH,
        )
        requests.append(
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sid,
                        "index": 0,
                        "hidden": False,
                        "gridProperties": {
                            "rowCount": height,
                            "columnCount": width,
                            "frozenRowCount": 1,
                            "frozenColumnCount": 1,
                        },
                    },
                    "fields": "index,hidden,gridProperties.rowCount,gridProperties.columnCount,gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
                }
            }
        )
        if missing:
            requests.append(
                {
                    "updateCells": {
                        "start": {"sheetId": sid, "rowIndex": 0, "columnIndex": len(headers)},
                        "rows": [cells(missing)],
                        "fields": "userEnteredValue",
                    }
                }
            )
        complete = headers + missing
        # Move whole named columns, preserving populated cells and user-added columns.
        for destination, column in enumerate(MASTER_COLUMNS):
            position = complete.index(column)
            if position != destination:
                requests.append(
                    {
                        "moveDimension": {
                            "source": {
                                "sheetId": sid,
                                "dimension": "COLUMNS",
                                "startIndex": position,
                                "endIndex": position + 1,
                            },
                            "destinationIndex": destination,
                        }
                    }
                )
                complete.insert(destination, complete.pop(position))
        requests.extend(
            [
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sid,
                            "startRowIndex": 1,
                            "endRowIndex": height,
                            "endColumnIndex": OWNED_WIDTH,
                        },
                        "cell": {"userEnteredFormat": {"verticalAlignment": "TOP", "wrapStrategy": "WRAP"}},
                        "fields": "userEnteredFormat.verticalAlignment,userEnteredFormat.wrapStrategy",
                    }
                },
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sid,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "endColumnIndex": OWNED_WIDTH,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {"bold": True},
                                "backgroundColor": {"red": 0.88, "green": 0.93, "blue": 0.88},
                                "verticalAlignment": "TOP",
                            }
                        },
                        "fields": "userEnteredFormat",
                    }
                },
                {
                    "setBasicFilter": {
                        "filter": {
                            "range": {
                                "sheetId": sid,
                                "startRowIndex": 0,
                                "endRowIndex": height,
                                "endColumnIndex": OWNED_WIDTH,
                            }
                        }
                    }
                },
                {
                    "updateDimensionProperties": {
                        "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 16},
                        "properties": {"hiddenByUser": False},
                        "fields": "hiddenByUser",
                    }
                },
                {
                    "updateDimensionProperties": {
                        "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 16, "endIndex": 20},
                        "properties": {"hiddenByUser": True},
                        "fields": "hiddenByUser",
                    }
                },
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sid,
                            "startRowIndex": 1,
                            "endRowIndex": height,
                            "startColumnIndex": 10,
                            "endColumnIndex": 11,
                        },
                        "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0%"}}},
                        "fields": "userEnteredFormat.numberFormat",
                    }
                },
            ]
        )
        for index, width in enumerate(WIDTHS):
            requests.append(
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sid,
                            "dimension": "COLUMNS",
                            "startIndex": index,
                            "endIndex": index + 1,
                        },
                        "properties": {"pixelSize": width},
                        "fields": "pixelSize",
                    }
                }
            )
        requests.extend(
            [
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sid,
                            "dimension": "COLUMNS",
                            "startIndex": 20,
                            "endIndex": ROW_ID_INDEX,
                        },
                        "properties": {"hiddenByUser": False, "pixelSize": 190},
                        "fields": "hiddenByUser,pixelSize",
                    }
                },
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sid,
                            "dimension": "COLUMNS",
                            "startIndex": ROW_ID_INDEX,
                            "endIndex": OWNED_WIDTH,
                        },
                        "properties": {"hiddenByUser": True},
                        "fields": "hiddenByUser",
                    }
                },
            ]
        )
        owned = {(c, v) for c, v, _ in COLORS}
        for index, rule in reversed(list(enumerate(master.get("conditionalFormats", []) if master else []))):
            condition = rule.get("booleanRule", {}).get("condition", {})
            values = condition.get("values", [])
            ranges = rule.get("ranges", [])
            if (
                condition.get("type") == "TEXT_EQ"
                and values
                and ranges
                and (ranges[0].get("startColumnIndex"), values[0].get("userEnteredValue")) in owned
            ):
                requests.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": index}})
        for index, (column_index, value, color) in enumerate(COLORS):
            requests.append(
                {
                    "addConditionalFormatRule": {
                        "index": index,
                        "rule": {
                            "ranges": [
                                {
                                    "sheetId": sid,
                                    "startRowIndex": 1,
                                    "endRowIndex": height,
                                    "startColumnIndex": column_index,
                                    "endColumnIndex": column_index + 1,
                                }
                            ],
                            "booleanRule": {
                                "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": value}]},
                                "format": {
                                    "backgroundColor": dict(zip(["red", "green", "blue"], color, strict=True))
                                },
                            },
                        },
                    }
                }
            )
        if created:
            requests.append(
                {
                    "addProtectedRange": {
                        "protectedRange": {
                            "range": {"sheetId": sid},
                            "description": "Generated LeadOS overview. Record approvals and feedback in the LeadOS dashboard.",
                            "warningOnly": True,
                        }
                    }
                }
            )
        self.client.batch_update(requests)
        _, _, master, raw = self._read()
        if not master or not raw or raw[0][:OWNED_WIDTH] != MASTER_COLUMNS:
            raise StorageError("master_view_structure_invalid")
        return {"created": created, "tab": MASTER_TAB, "headers_valid": True}

    def _timestamp(self, master):
        return next(
            (m for m in master.get("developerMetadata", []) if m.get("metadataKey") == SYNC_KEY), None
        )

    def sync(self, rows: list[dict]):
        if len(rows) > self.config.sheets_max_rows:
            raise StorageError("master_view_row_limit")
        wanted = {row_identity(r): r for r in rows}
        if len(wanted) != len(rows):
            raise StorageError("master_view_duplicate_projection")
        for attempt in range(self.config.sheets_max_attempts):
            try:
                _, sheets, master, raw = self._read()
                if not master or not raw or raw[0][:OWNED_WIDTH] != MASTER_COLUMNS:
                    self.initialize()
                    _, sheets, master, raw = self._read()
                assert master is not None
                sid = master["properties"]["sheetId"]
                positions = {}
                stale = []
                order = []
                requests = []
                changed = 0
                for number, row in enumerate(raw[1:], 1):
                    padded = row[:OWNED_WIDTH] + [""] * max(0, OWNED_WIDTH - len(row))
                    oid = str(padded[ROW_ID_INDEX] or padded[16])
                    if not any(padded):
                        continue
                    if oid in positions or oid not in wanted:
                        stale.append(number)
                    else:
                        positions[oid] = (number, padded)
                        order.append(oid)
                for oid, row in wanted.items():
                    if oid in positions and positions[oid][1] != flat_values(row):
                        requests.append(self._update(sid, positions[oid][0], row))
                        changed += 1
                new = [r for r in rows if row_identity(r) not in positions]
                if new:
                    requests.append(
                        {
                            "appendCells": {
                                "sheetId": sid,
                                "rows": [self._cells(r) for r in new],
                                "fields": "userEnteredValue,userEnteredFormat.textFormat.link",
                            }
                        }
                    )
                for number in stale:
                    requests.append(
                        {
                            "updateCells": {
                                "start": {"sheetId": sid, "rowIndex": number, "columnIndex": 0},
                                "rows": [cells([""] * OWNED_WIDTH)],
                                "fields": "userEnteredValue,userEnteredFormat.textFormat.link",
                            }
                        }
                    )
                # Put generated rows contiguously below the header in the
                # projection's deterministic order. Google's empty-cell sort
                # semantics can otherwise leave unscored prospects among
                # retired blank rows. Move whole rows to retain user columns.
                slots: list[str | None] = [None] * max(len(raw), 1)
                for oid, (number, _) in positions.items():
                    slots[number] = oid
                slots.extend(row_identity(row) for row in new)
                for destination, oid in enumerate(wanted, 1):
                    position = slots.index(oid)
                    if position != destination:
                        requests.append(
                            {
                                "moveDimension": {
                                    "source": {
                                        "sheetId": sid,
                                        "dimension": "ROWS",
                                        "startIndex": position,
                                        "endIndex": position + 1,
                                    },
                                    "destinationIndex": destination,
                                }
                            }
                        )
                        slots.insert(destination, slots.pop(position))
                for title, sheet in sheets.items():
                    props = sheet["properties"]
                    hidden = (
                        title not in {MASTER_TAB, "LEADOS_DISCOVERY_RESULTS"}
                        and not self.config.show_technical_sheets
                    )
                    if props.get("hidden", False) != hidden or (
                        title == MASTER_TAB and props.get("index", 0) != 0
                    ):
                        update = {"sheetId": props["sheetId"], "hidden": hidden}
                        if title == MASTER_TAB:
                            update["index"] = 0
                        requests.append(
                            {
                                "updateSheetProperties": {
                                    "properties": update,
                                    "fields": "hidden,index" if title == MASTER_TAB else "hidden",
                                }
                            }
                        )
                metadata = self._timestamp(master)
                last_synced = metadata.get("metadataValue") if metadata else None
                if requests or not metadata:
                    last_synced = utc_now()
                    if metadata:
                        requests.append(
                            {
                                "updateDeveloperMetadata": {
                                    "dataFilters": [
                                        {"developerMetadataLookup": {"metadataId": metadata["metadataId"]}}
                                    ],
                                    "developerMetadata": {"metadataValue": last_synced},
                                    "fields": "metadataValue",
                                }
                            }
                        )
                    else:
                        requests.append(
                            {
                                "createDeveloperMetadata": {
                                    "developerMetadata": {
                                        "metadataKey": SYNC_KEY,
                                        "metadataValue": last_synced,
                                        "location": {"sheetId": sid},
                                        "visibility": "DOCUMENT",
                                    }
                                }
                            }
                        )
                    if len(json.dumps(requests).encode()) > 1_800_000:
                        raise StorageError("master_view_batch_too_large")
                    self.client.batch_update(requests)
                return {
                    "provider": "google_sheets",
                    "rows": len(rows),
                    "expected_rows": len(rows),
                    "duplicates": 0,
                    "last_synced_at": last_synced,
                    "technical_sheets_hidden": not self.config.show_technical_sheets,
                    "master_view_visible": True,
                    "headers_valid": True,
                    "rows_match": True,
                    "valid": True,
                    "created_rows": len(new),
                    "updated_rows": changed,
                    "retired_rows": len(stale),
                    "retries": attempt,
                }
            except StorageError as exc:
                if not exc.retryable or attempt + 1 == self.config.sheets_max_attempts:
                    raise
                # Re-read UUIDs/content before retrying an ambiguous append response.
                time.sleep(max(exc.retry_after, min(0.25 * 2**attempt, 5)))
        raise StorageError("master_view_sync_failed")

    def _cells(self, row):
        result = cells(flat_values(row))
        if row["source"]:
            result["values"][12]["userEnteredFormat"] = {"textFormat": {"link": {"uri": row["source"]}}}
        return result

    def _update(self, sid, number, row):
        return {
            "updateCells": {
                "start": {"sheetId": sid, "rowIndex": number, "columnIndex": 0},
                "rows": [self._cells(row)],
                "fields": "userEnteredValue,userEnteredFormat.textFormat.link",
            }
        }

    def status(self, expected: list[dict]):
        _, sheets, master, raw = self._read()
        if not master:
            return {
                "provider": "google_sheets",
                "rows": 0,
                "expected_rows": len(expected),
                "last_synced_at": None,
                "duplicates": 0,
                "valid": False,
                "error": {"code": "master_view_missing"},
            }
        headers_valid = bool(raw and raw[0][:OWNED_WIDTH] == MASTER_COLUMNS)
        values = [
            r[:OWNED_WIDTH] + [""] * max(0, OWNED_WIDTH - len(r)) for r in raw[1:] if any(r[:OWNED_WIDTH])
        ]
        ids = [str(r[ROW_ID_INDEX] or r[16]) for r in values]
        duplicates = sum(n - 1 for n in Counter(ids).values())
        props = master["properties"]
        hidden = all(sheets[t]["properties"].get("hidden", False) for t in SCHEMAS)
        visibility_valid = all(
            s["properties"].get("hidden", False)
            == (t not in {MASTER_TAB, "LEADOS_DISCOVERY_RESULTS"} and not self.config.show_technical_sheets)
            for t, s in sheets.items()
        )
        helpers = [c for d in master.get("data", []) for c in d.get("columnMetadata", [])][16:20]
        identity_helper = [c for d in master.get("data", []) for c in d.get("columnMetadata", [])][
            ROW_ID_INDEX:OWNED_WIDTH
        ]
        helpers_hidden = (
            len(helpers) == 4
            and all(c.get("hiddenByUser", False) for c in helpers)
            and len(identity_helper) == 1
            and identity_helper[0].get("hiddenByUser", False)
        )

        # Google may order indistinguishable empty score/date cells differently.
        # Compare contents by stable identity; still enforce meaningful score/date order.
        def identity(value):
            return str(value[ROW_ID_INDEX] or value[16])

        matches = sorted(values, key=identity) == sorted([flat_values(r) for r in expected], key=identity)
        ranks = [(r[8] or 0, r[4]) for r in values]
        ranking_valid = ranks == sorted(ranks, reverse=True)
        populated_positions = [i for i, r in enumerate(raw[1:], 1) if any(r[:OWNED_WIDTH])]
        rows_contiguous = populated_positions == list(range(1, len(values) + 1))
        metadata = self._timestamp(master)
        return {
            "provider": "google_sheets",
            "rows": len(values),
            "expected_rows": len(expected),
            "last_synced_at": metadata.get("metadataValue") if metadata else None,
            "duplicates": duplicates,
            "technical_sheets_hidden": hidden,
            "visibility_valid": visibility_valid,
            "master_view_visible": not props.get("hidden", False),
            "master_view_first": props.get("index") == 0,
            "helper_columns_hidden": helpers_hidden,
            "headers_valid": headers_valid,
            "rows_match": matches,
            "ranking_valid": ranking_valid,
            "rows_contiguous": rows_contiguous,
            "valid": headers_valid
            and matches
            and ranking_valid
            and rows_contiguous
            and not duplicates
            and visibility_valid
            and helpers_hidden
            and props.get("index") == 0,
        }
