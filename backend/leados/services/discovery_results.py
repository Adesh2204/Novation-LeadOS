"""Visible research projection, separate from qualified opportunities and scoring."""

import json

from leados.services.master_view_sync import writer_for
from leados.services.prospects import live_prospects
from leados.storage.base import StorageError, StorageProvider
from leados.storage.google_sheets import GoogleSheetsStorageProvider, cells
from leados.storage.master_view_writer import atomic_json
from leados.storage.mock import MockStorageProvider
from leados.storage.records import ProviderRun
from leados.storage.workbook import column_name

DISCOVERY_TAB = "LEADOS_DISCOVERY_RESULTS"
DISCOVERY_COLUMNS = [
    "run_id",
    "company",
    "source_url",
    "published_date",
    "status",
    "relevance",
    "reason",
    "source_excerpt",
    "opportunity_ids",
    "preview",
    "retrieved_at",
    "record_origin",
    "organization_role",
    "service_demand",
    "commercial_fit",
    "qualification_method",
    "qualification_version",
    "firecrawl_decision",
    "provider_score",
    "evidence_confidence",
    "signal_confidence",
    "trigger",
    "vertical",
    "recommended_service",
    "research_status",
]


def discovery_rows(storage: StorageProvider) -> list[dict]:
    rows = []
    source_prospects = {s["url"]: p for p in live_prospects(storage) for s in p["sources"]}
    for run in sorted(storage.list(ProviderRun), key=lambda item: item.created_at, reverse=True):
        for result in run.state.get("discovery_results", []):
            if result.get("record_origin") != "LIVE":
                continue
            qualification = result.get("qualification", {})
            prospect = result.get("prospect") or source_prospects.get(result.get("source_url", ""), {})
            rows.append(
                {
                    **{
                        key: prospect.get(key, "")
                        for key in ("trigger", "vertical", "recommended_service", "research_status")
                    },
                    "research_status": result.get(
                        "research_status", prospect.get("research_status", "NEEDS_RESEARCH")
                    ),
                    "run_id": run.id,
                    "company": result.get("company", ""),
                    "source_url": result.get("source_url", ""),
                    "published_date": result.get("published_date") or "",
                    "status": result.get("status", "NEEDS_RESEARCH"),
                    "relevance": result.get("relevance", 0),
                    "reason": result.get("reason", ""),
                    "source_excerpt": result.get("snippet", ""),
                    "opportunity_ids": ", ".join(result.get("opportunity_ids", [])),
                    "preview": bool(run.state.get("dry_run", False)),
                    "retrieved_at": run.created_at.isoformat(),
                    "record_origin": "LIVE",
                    "organization_role": qualification.get("organization_role", "UNCERTAIN"),
                    "service_demand": qualification.get("service_demand", False),
                    "commercial_fit": qualification.get("commercial_fit", "UNVERIFIED"),
                    "qualification_method": qualification.get("method", "NOT_RECORDED"),
                    "qualification_version": qualification.get("version", ""),
                    "firecrawl_decision": result.get("firecrawl_decision", "NEEDS_ADDITIONAL_RESEARCH"),
                    "provider_score": result.get("provider_score") or "",
                    "evidence_confidence": qualification.get("evidence_confidence", 0),
                    "signal_confidence": qualification.get("signal_confidence", 0),
                }
            )
    return rows


def sync_discovery_results(storage: StorageProvider) -> dict:
    rows = discovery_rows(storage)
    if isinstance(storage, MockStorageProvider):
        if storage.path:
            atomic_json(
                storage.path.with_name(storage.path.stem + "-discovery-results.json"),
                {
                    "tab": DISCOVERY_TAB,
                    "columns": DISCOVERY_COLUMNS,
                    "rows": rows,
                },
            )
        return {"discovery_rows": len(rows), "discovery_synced": True}
    if not isinstance(storage, GoogleSheetsStorageProvider):
        return {"discovery_rows": len(rows), "discovery_synced": True}
    if len(rows) > storage.config.sheets_max_rows:
        raise StorageError("discovery_projection_row_limit")
    client = storage.client
    metadata = writer_for(storage).metadata()
    sheets = {sheet["properties"]["title"]: sheet["properties"] for sheet in metadata["sheets"]}
    existing = sheets.get(DISCOVERY_TAB)
    width = len(DISCOVERY_COLUMNS)
    wanted = [DISCOVERY_COLUMNS, *[[row.get(column, "") for column in DISCOVERY_COLUMNS] for row in rows]]
    requests: list[dict] = []
    raw = []
    if existing:
        raw = client.batch_read(
            [
                f"'{DISCOVERY_TAB}'!A1:{column_name(max(width, existing.get('gridProperties', {}).get('columnCount', width)))}{storage.config.sheets_max_rows + 2}"
            ]
        )[0]
        if raw and raw[0][:11] != DISCOVERY_COLUMNS[:11]:
            raise StorageError("discovery_projection_header_conflict")
        if raw and raw[0] != DISCOVERY_COLUMNS:
            if raw[0] != DISCOVERY_COLUMNS[: len(raw[0])]:
                raise StorageError("discovery_projection_header_conflict")
            requests.append(
                {
                    "updateCells": {
                        "start": {"sheetId": existing["sheetId"], "rowIndex": 0, "columnIndex": len(raw[0])},
                        "rows": [cells(DISCOVERY_COLUMNS[len(raw[0]) :])],
                        "fields": "userEnteredValue",
                    }
                }
            )
        if raw == wanted and not existing.get("hidden", False):
            return {"discovery_rows": len(rows), "discovery_synced": True}
        sid = existing["sheetId"]
    else:
        used = {sheet["sheetId"] for sheet in sheets.values()}
        sid = next(i for i in range(100, 10000) if i not in used)
        requests.append(
            {
                "addSheet": {
                    "properties": {
                        "sheetId": sid,
                        "title": DISCOVERY_TAB,
                        "gridProperties": {"rowCount": max(1000, len(wanted) + 1), "columnCount": width},
                    }
                }
            }
        )
    if not raw:
        requests.append(
            {
                "updateCells": {
                    "start": {"sheetId": sid, "rowIndex": 0},
                    "rows": [cells(DISCOVERY_COLUMNS)],
                    "fields": "userEnteredValue",
                }
            }
        )
    actual = {}
    duplicates = []
    for position, values in enumerate(raw[1:], 1):
        if not any(values):
            continue
        padded = values[:width] + [""] * max(0, width - len(values))
        key = tuple(str(value) for value in padded[:3])
        if key in actual:
            duplicates.append(position)
        else:
            actual[key] = (position, padded)
    needed = {tuple(str(value) for value in values[:3]) for values in wanted[1:]}
    new = []
    for values in wanted[1:]:
        key = tuple(str(value) for value in values[:3])
        stored = actual.get(key)
        if stored is None:
            new.append(values)
        elif stored[1] != values:
            requests.append(
                {
                    "updateCells": {
                        "start": {"sheetId": sid, "rowIndex": stored[0]},
                        "rows": [cells(values)],
                        "fields": "userEnteredValue",
                    }
                }
            )
    stale = [position for key, (position, _) in actual.items() if key not in needed]
    for position in [*stale, *duplicates]:
        requests.append(
            {
                "updateCells": {
                    "range": {
                        "sheetId": sid,
                        "startRowIndex": position,
                        "endRowIndex": position + 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": width,
                    },
                    "fields": "userEnteredValue",
                }
            }
        )
    # Append at explicit row positions. Re-reading makes retries safe after an ambiguous write.
    start_row = max(1, len(raw))
    end_row = max(len(wanted), start_row + len(new))
    for offset in range(0, len(new), 100):
        requests.append(
            {
                "updateCells": {
                    "start": {"sheetId": sid, "rowIndex": start_row + offset},
                    "rows": [cells(values) for values in new[offset : offset + 100]],
                    "fields": "userEnteredValue",
                }
            }
        )
    properties = existing.get("gridProperties", {}) if existing else {}
    requests.insert(
        1 if not existing else 0,
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sid,
                    "hidden": False,
                    "gridProperties": {
                        "rowCount": max(properties.get("rowCount", 1000), end_row + 1),
                        "columnCount": max(properties.get("columnCount", width), width),
                        "frozenRowCount": 1,
                    },
                },
                "fields": "hidden,gridProperties.rowCount,gridProperties.columnCount,gridProperties.frozenRowCount",
            }
        },
    )
    if end_row > 2:
        requests.append(
            {
                "sortRange": {
                    "range": {
                        "sheetId": sid,
                        "startRowIndex": 1,
                        "endRowIndex": end_row,
                        "endColumnIndex": width,
                    },
                    "sortSpecs": [{"dimensionIndex": 10, "sortOrder": "DESCENDING"}],
                }
            }
        )
    requests.append(
        {
            "repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True},
                        "backgroundColor": {"red": 0.88, "green": 0.94, "blue": 0.84},
                    }
                },
                "fields": "userEnteredFormat",
            }
        }
    )
    batch: list[dict] = []
    size = 0
    for request in requests:
        request_size = len(json.dumps(request).encode())
        if request_size > 1_800_000:
            raise StorageError("discovery_projection_row_too_large")
        if batch and size + request_size > 900_000:
            client.batch_update(batch)
            batch, size = [], 0
        batch.append(request)
        size += request_size
    if batch:
        client.batch_update(batch)
    return {"discovery_rows": len(rows), "discovery_synced": True}
