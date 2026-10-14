"""Non-destructive workbook initialization (explicit command only)."""

from leados.storage.base import StorageError
from leados.storage.google_sheets import cells
from leados.storage.workbook import (
    ENUMS,
    FEEDBACK_REASONS,
    FEEDBACK_STATUSES,
    SCHEMAS,
    WORKBOOK_NAME,
    column_name,
)


def initialize_workbook(client, *, max_rows=10000):
    metadata = client.metadata()
    if metadata["properties"]["title"] != WORKBOOK_NAME:
        raise StorageError("wrong_workbook_title", f"Name spreadsheet {WORKBOOK_NAME} first")
    existing = {s["properties"]["title"]: s["properties"] for s in metadata["sheets"]}
    old_tabs = [t for t in SCHEMAS if t in existing]
    raw = (
        client.batch_read(
            [
                f"'{t}'!A1:{column_name(existing[t].get('gridProperties', {}).get('columnCount', 26))}1"
                for t in old_tabs
            ]
        )
        if old_tabs
        else []
    )
    current = {t: (v[0] if v else []) for t, v in zip(old_tabs, raw, strict=True)}
    used = {p["sheetId"] for p in existing.values()}
    requests: list[dict] = []
    added = []
    for tab, schema in SCHEMAS.items():
        if tab in existing:
            sheet_id = existing[tab]["sheetId"]
        else:
            sheet_id = next(i for i in range(100, 10000) if i not in used)
            used.add(sheet_id)
            added.append(tab)
            requests.append(
                {
                    "addSheet": {
                        "properties": {
                            "sheetId": sheet_id,
                            "title": tab,
                            "gridProperties": {
                                "rowCount": max_rows + 2,
                                "columnCount": max(26, len(schema.headers)),
                            },
                        }
                    }
                }
            )
        headers = current.get(tab, [])
        if len(headers) != len(set(headers)):
            raise StorageError("duplicate_header", tab)
        missing = [h for h in schema.headers if h not in headers]
        width = max(
            26,
            len(headers) + len(missing),
            existing.get(tab, {}).get("gridProperties", {}).get("columnCount", 26),
        )
        height = max(max_rows + 2, existing.get(tab, {}).get("gridProperties", {}).get("rowCount", 0))
        requests.append(
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "gridProperties": {"frozenRowCount": 1, "columnCount": width, "rowCount": height},
                    },
                    "fields": "gridProperties",
                }
            }
        )
        if missing:
            requests.append(
                {
                    "updateCells": {
                        "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": len(headers)},
                        "rows": [cells(missing)],
                        "fields": "userEnteredValue",
                    }
                }
            )
        complete = headers + missing
        requests.extend(
            [
                {
                    "repeatCell": {
                        "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {"bold": True},
                                "backgroundColor": {"red": 0.88, "green": 0.93, "blue": 0.88},
                            }
                        },
                        "fields": "userEnteredFormat",
                    }
                },
                {
                    "setBasicFilter": {
                        "filter": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": 0,
                                "endRowIndex": height,
                                "endColumnIndex": len(complete),
                            }
                        }
                    }
                },
            ]
        )
        for column, allowed in ENUMS.items():
            if column in complete:
                pos = complete.index(column)
                requests.append(
                    {
                        "setDataValidation": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": 1,
                                "endRowIndex": height,
                                "startColumnIndex": pos,
                                "endColumnIndex": pos + 1,
                            },
                            "rule": {
                                "condition": {
                                    "type": "ONE_OF_LIST",
                                    "values": [{"userEnteredValue": v} for v in allowed],
                                },
                                "strict": True,
                                "showCustomUi": True,
                            },
                        }
                    }
                )
        if tab == "FEEDBACK":
            for column, allowed in [("status", FEEDBACK_STATUSES), ("reason", FEEDBACK_REASONS)]:
                pos = complete.index(column)
                requests.append(
                    {
                        "setDataValidation": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": 1,
                                "endRowIndex": height,
                                "startColumnIndex": pos,
                                "endColumnIndex": pos + 1,
                            },
                            "rule": {
                                "condition": {
                                    "type": "ONE_OF_LIST",
                                    "values": [{"userEnteredValue": v} for v in allowed],
                                },
                                "strict": True,
                                "showCustomUi": True,
                            },
                        }
                    }
                )
        # Warning protection avoids changing users' existing sharing/ownership rights.
        # Add only on newly created tabs to avoid accumulating duplicate protections.
        if tab in added:
            id_column = "snapshot_id" if tab == "PROVIDER_RUNS" else schema.aliases.get("id", "id")
            pos = complete.index(id_column)
            requests.append(
                {
                    "addProtectedRange": {
                        "protectedRange": {
                            "range": {
                                "sheetId": sheet_id,
                                "startColumnIndex": pos,
                                "endColumnIndex": pos + 1,
                            },
                            "description": "LeadOS immutable UUID; edit through backend",
                            "warningOnly": True,
                        }
                    }
                }
            )
            if tab == "OPPORTUNITIES":
                band = complete.index("score_band")
                for index, (value, color) in enumerate(
                    [
                        ("HOT", {"red": 0.8, "green": 0.92, "blue": 0.65}),
                        ("STRONG", {"red": 0.91, "green": 0.95, "blue": 0.82}),
                        ("MONITOR", {"red": 0.95, "green": 0.95, "blue": 0.95}),
                        ("IGNORE", {"red": 0.89, "green": 0.89, "blue": 0.89}),
                    ]
                ):
                    requests.append(
                        {
                            "addConditionalFormatRule": {
                                "index": index,
                                "rule": {
                                    "ranges": [
                                        {
                                            "sheetId": sheet_id,
                                            "startRowIndex": 1,
                                            "endRowIndex": height,
                                            "startColumnIndex": band,
                                            "endColumnIndex": band + 1,
                                        }
                                    ],
                                    "booleanRule": {
                                        "condition": {
                                            "type": "TEXT_EQ",
                                            "values": [{"userEnteredValue": value}],
                                        },
                                        "format": {"backgroundColor": color},
                                    },
                                },
                            }
                        }
                    )
    client.batch_update(requests)
    return {
        "workbook": WORKBOOK_NAME,
        "tabs": list(SCHEMAS),
        "created_tabs": added,
        "existing_data_deleted": False,
    }
