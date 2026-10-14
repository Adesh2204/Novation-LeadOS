"""In-memory Google Sheets emulator for storage tests; never opens a network."""

import copy
import re
from collections import Counter
from functools import cmp_to_key
from threading import RLock

from leados.storage.base import StorageError
from leados.storage.workbook import WORKBOOK_NAME


class MockGoogleSheetsClient:
    def __init__(self):
        self.spreadsheet_id = "synthetic-workbook"
        self.title = WORKBOOK_NAME
        self.tabs: dict[str, dict] = {}
        self.calls: list[dict] = []
        self.failures: list[str] = []
        self.metrics: Counter = Counter()
        self._lock = RLock()
        self.fail_after_commit = False

    def _maybe_fail(self):
        if self.failures:
            code = self.failures.pop(0)
            raise StorageError(
                code, retryable=code in {"quota_exceeded", "storage_timeout", "google_api_unavailable"}
            )

    def metadata(self, *, fields=None, ranges=None):
        self._maybe_fail()
        self.calls.append({"method": "metadata"})
        included = {item.split("!")[0].strip("'") for item in ranges} if ranges else None
        return {
            "spreadsheetId": self.spreadsheet_id,
            "properties": {"title": self.title},
            "sheets": [
                {
                    "properties": {
                        "sheetId": v["id"],
                        "title": k,
                        "index": i,
                        "hidden": v.get("properties", {}).get("hidden", False),
                        "gridProperties": {
                            "rowCount": 10002,
                            "columnCount": 100,
                            **v.get("properties", {}).get("gridProperties", {}),
                        },
                    },
                    "conditionalFormats": copy.deepcopy(v.get("conditional_formats", [])),
                    "developerMetadata": copy.deepcopy(v.get("developer_metadata", [])),
                    "data": [
                        {
                            "startColumn": 0,
                            "columnMetadata": [
                                v.get("columns", {}).get(str(c), {})
                                for c in range(
                                    v.get("properties", {}).get("gridProperties", {}).get("columnCount", 20)
                                )
                            ],
                        }
                    ],
                }
                for i, (k, v) in enumerate(self.tabs.items())
                if included is None or k in included
            ],
        }

    def batch_read(self, ranges):
        self._maybe_fail()
        self.metrics["batch_reads"] += 1
        self.calls.append({"method": "batch_read", "ranges": ranges})
        result = []
        for item in ranges:
            tab = item.split("!")[0].strip("'")
            if tab not in self.tabs:
                raise StorageError("missing_sheet", tab)
            match = re.search(r"!([A-Z]+)(\d+):([A-Z]+)(\d+)$", item)
            values = self.tabs[tab]["rows"]
            if match:

                def col(value):
                    n = 0
                    for character in value:
                        n = n * 26 + ord(character) - 64
                    return n

                left, top, right, bottom = match.groups()
                values = [row[col(left) - 1 : col(right)] for row in values[int(top) - 1 : int(bottom)]]
            result.append(copy.deepcopy(values))
        return result

    def read_range(self, range_name):
        return self.batch_read([range_name])[0]

    def batch_update(self, requests):
        self._maybe_fail()
        with self._lock:
            staged = copy.deepcopy(self.tabs)
            for request in requests:
                if "addSheet" in request:
                    props = request["addSheet"]["properties"]
                    staged[props["title"]] = {
                        "id": props["sheetId"],
                        "rows": [],
                        "properties": copy.deepcopy(props),
                    }
                elif "updateSheetProperties" in request:
                    props = request["updateSheetProperties"]["properties"]
                    name, tab = next((k, v) for k, v in staged.items() if v["id"] == props["sheetId"])
                    stored = tab.setdefault("properties", {})
                    for key, value in props.items():
                        if key == "gridProperties":
                            stored.setdefault(key, {}).update(value)
                        else:
                            stored[key] = value
                    if "index" in props:
                        ordered = list(staged.items())
                        ordered = [(k, v) for k, v in ordered if k != name]
                        ordered.insert(props["index"], (name, tab))
                        staged = dict(ordered)
                elif "updateDimensionProperties" in request:
                    op = request["updateDimensionProperties"]
                    tab = next(v for v in staged.values() if v["id"] == op["range"]["sheetId"])
                    target = tab.setdefault(
                        "columns" if op["range"]["dimension"] == "COLUMNS" else "row_properties", {}
                    )
                    for index in range(op["range"]["startIndex"], op["range"]["endIndex"]):
                        target.setdefault(str(index), {}).update(op["properties"])
                elif "moveDimension" in request:
                    op = request["moveDimension"]
                    tab = next(v for v in staged.values() if v["id"] == op["source"]["sheetId"])
                    start, end = op["source"]["startIndex"], op["source"]["endIndex"]
                    destination = op["destinationIndex"]
                    if destination > start:
                        destination -= end - start
                    if op["source"]["dimension"] == "ROWS":
                        moved = tab["rows"][start:end]
                        del tab["rows"][start:end]
                        tab["rows"][destination:destination] = moved
                        for key in ("cell_data", "row_properties"):
                            stored = tab.get(key, {})
                            remapped = {}
                            for index, value in stored.items():
                                row_index, _, column = index.partition(",")
                                number = int(row_index)
                                if start <= number < end:
                                    number = destination + number - start
                                else:
                                    if number >= end:
                                        number -= end - start
                                    if number >= destination:
                                        number += end - start
                                remapped[str(number) + ("," + column if column else "")] = value
                            if stored:
                                tab[key] = remapped
                    else:
                        for row in tab["rows"]:
                            while len(row) < end:
                                row.append("")
                            moved = row[start:end]
                            del row[start:end]
                            row[destination:destination] = moved
                elif "setBasicFilter" in request:
                    op = request["setBasicFilter"]["filter"]
                    tab = next(v for v in staged.values() if v["id"] == op["range"]["sheetId"])
                    tab["basic_filter"] = copy.deepcopy(op)
                elif "addConditionalFormatRule" in request:
                    op = request["addConditionalFormatRule"]
                    tab = next(v for v in staged.values() if v["id"] == op["rule"]["ranges"][0]["sheetId"])
                    tab.setdefault("conditional_formats", []).insert(op["index"], copy.deepcopy(op["rule"]))
                elif "deleteConditionalFormatRule" in request:
                    op = request["deleteConditionalFormatRule"]
                    tab = next(v for v in staged.values() if v["id"] == op["sheetId"])
                    del tab.setdefault("conditional_formats", [])[op["index"]]
                elif "createDeveloperMetadata" in request:
                    op = copy.deepcopy(request["createDeveloperMetadata"]["developerMetadata"])
                    tab = next(v for v in staged.values() if v["id"] == op["location"]["sheetId"])
                    op["metadataId"] = (
                        max(
                            (
                                m["metadataId"]
                                for v in staged.values()
                                for m in v.get("developer_metadata", [])
                            ),
                            default=0,
                        )
                        + 1
                    )
                    tab.setdefault("developer_metadata", []).append(op)
                elif "updateDeveloperMetadata" in request:
                    op = request["updateDeveloperMetadata"]
                    mid = op["dataFilters"][0]["developerMetadataLookup"]["metadataId"]
                    for tab in staged.values():
                        for metadata in tab.get("developer_metadata", []):
                            if metadata["metadataId"] == mid:
                                metadata.update(op["developerMetadata"])
                elif "sortRange" in request:
                    op = request["sortRange"]
                    tab = next(v for v in staged.values() if v["id"] == op["range"]["sheetId"])
                    start, end = (
                        op["range"].get("startRowIndex", 0),
                        op["range"].get("endRowIndex", len(tab["rows"])),
                    )

                    def compare(a, b, specifications=op["sortSpecs"]):
                        for spec in specifications:
                            c = spec["dimensionIndex"]
                            x, y = a[c] if c < len(a) else "", b[c] if c < len(b) else ""
                            if x == y:
                                continue
                            if x == "":
                                return 1
                            if y == "":
                                return -1
                            order = (x > y) - (x < y)
                            return -order if spec["sortOrder"] == "DESCENDING" else order
                        return 0

                    tab["rows"][start:end] = sorted(tab["rows"][start:end], key=cmp_to_key(compare))
                elif "updateSpreadsheetProperties" in request:
                    self.title = request["updateSpreadsheetProperties"]["properties"]["title"]
                elif "updateCells" in request or "appendCells" in request:
                    append = "appendCells" in request
                    operation = request.get("appendCells", request.get("updateCells"))
                    start = operation.get("start", operation.get("range", {}))
                    sheet_id = operation.get("sheetId", start.get("sheetId"))
                    tab = next(v for v in staged.values() if v["id"] == sheet_id)
                    row_index = (
                        len(tab["rows"]) if append else start.get("rowIndex", start.get("startRowIndex", 0))
                    )
                    column_index = start.get("columnIndex", start.get("startColumnIndex", 0))
                    for offset, r in enumerate(operation["rows"]):
                        while len(tab["rows"]) <= row_index + offset:
                            tab["rows"].append([])
                        values = [
                            next(iter(c.get("userEnteredValue", {"stringValue": ""}).values()))
                            for c in r["values"]
                        ]
                        target = tab["rows"][row_index + offset]
                        while len(target) < column_index + len(values):
                            target.append("")
                        if "userEnteredValue" in operation.get("fields", "userEnteredValue"):
                            target[column_index : column_index + len(values)] = values
                        for column, value in enumerate(r["values"], column_index):
                            tab.setdefault("cell_data", {})[f"{row_index + offset},{column}"] = copy.deepcopy(
                                value
                            )
            self.tabs = staged
            self.calls.append({"method": "batch_update", "requests": copy.deepcopy(requests)})
            self.metrics["batch_writes"] += 1
            if self.fail_after_commit:
                self.fail_after_commit = False
                raise StorageError("storage_timeout", retryable=True)
        return {"replies": [{} for _ in requests]}

    def close(self):
        pass
