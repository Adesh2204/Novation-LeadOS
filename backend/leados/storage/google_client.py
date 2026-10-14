"""Small credential-isolated Sheets REST client with bounded reads/retries."""

import json
import time
from collections import Counter, deque
from threading import Lock
from typing import Any
from urllib.parse import quote

import httpx

from leados.config import Settings
from leados.storage.base import StorageError
from leados.storage.workbook import SHEETS_SCOPE, column_name


class GoogleSheetsClient:
    def __init__(self, config: Settings, *, transport=None, token_provider=None):
        if not config.google_sheets_enabled or not config.google_spreadsheet_id:
            raise StorageError("google_sheets_not_configured")
        self.config = config
        self.spreadsheet_id = config.google_spreadsheet_id
        self.http = httpx.Client(timeout=config.sheets_timeout_seconds, transport=transport)
        self.metrics: Counter = Counter()
        self._calls: deque = deque()
        self._lock = Lock()
        self._token_provider = token_provider or self._service_account_token
        self._credentials: Any = None

    def _service_account_token(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account

            if self._credentials is None:
                if self.config.google_service_account_json_path:
                    self._credentials = service_account.Credentials.from_service_account_file(
                        self.config.google_service_account_json_path, scopes=[SHEETS_SCOPE]
                    )
                elif self.config.google_service_account_json:
                    self._credentials = service_account.Credentials.from_service_account_info(
                        json.loads(self.config.google_service_account_json), scopes=[SHEETS_SCOPE]
                    )
                else:
                    raise StorageError("credentials_missing")
            if not self._credentials.valid:
                request = Request()
                self._credentials.refresh(
                    lambda *args, **kwargs: request(
                        *args, **{**kwargs, "timeout": self.config.sheets_timeout_seconds}
                    )
                )
            return self._credentials.token
        except StorageError:
            raise
        except Exception:
            raise StorageError("authentication_failed") from None

    def _request(self, method: str, suffix: str = "", *, params=None, body=None, retry=True):
        attempts = self.config.sheets_max_attempts if retry else 1
        for attempt in range(attempts):
            with self._lock:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= 60:
                    self._calls.popleft()
                if len(self._calls) >= self.config.sheets_requests_per_minute:
                    raise StorageError("local_quota_exceeded", retryable=True)
                self._calls.append(now)
            try:
                response = self.http.request(
                    method,
                    f"https://sheets.googleapis.com/v4/spreadsheets/{self.spreadsheet_id}{suffix}",
                    params=params,
                    json=body,
                    headers={"Authorization": "Bearer " + self._token_provider()},
                )
                self.metrics["requests"] += 1
                if response.is_success:
                    return response.json()
                codes = {
                    401: "authentication_failed",
                    403: "permission_denied",
                    404: "spreadsheet_not_found",
                    429: "quota_exceeded",
                }
                code = codes.get(
                    response.status_code,
                    "google_api_unavailable" if response.status_code >= 500 else "invalid_google_request",
                )
                transient = response.status_code == 429 or response.status_code >= 500
                try:
                    delay = min(float(response.headers.get("Retry-After", 0)), 10)
                except ValueError:
                    delay = 0
                error = StorageError(code, retryable=transient, retry_after=max(0, delay))
            except httpx.TimeoutException:
                error, delay = StorageError("storage_timeout", retryable=True), 0
            except httpx.RequestError:
                error, delay = StorageError("network_failure", retryable=True), 0
            if not error.retryable or attempt + 1 == attempts:
                raise error
            self.metrics["retries"] += 1
            time.sleep(max(delay, min(0.25 * 2**attempt, 5)))
        raise StorageError("google_api_unavailable")

    def metadata(self, *, fields="spreadsheetId,properties(title),sheets(properties)", ranges=None):
        params = [("fields", fields)]
        if ranges:
            params.extend(("ranges", item) for item in ranges)
        return self._request("GET", params=params)

    def read_range(self, range_name: str):
        return self.batch_read([range_name])[0]

    def batch_read(self, ranges: list[str]):
        self.metrics["batch_reads"] += 1
        data = self._request(
            "GET",
            "/values:batchGet",
            params=[
                *(("ranges", r) for r in ranges),
                ("valueRenderOption", "UNFORMATTED_VALUE"),
                ("dateTimeRenderOption", "FORMATTED_STRING"),
            ],
        )
        return [item.get("values", []) for item in data.get("valueRanges", [])]

    def batch_update(self, requests: list[dict]):
        # Append retries belong to the storage adapter, which reconciles commit UUIDs first.
        self.metrics["batch_writes"] += 1
        return self._request("POST", ":batchUpdate", body={"requests": requests}, retry=False)

    def batch_update_values(self, ranges: list[dict]):
        return self._request(
            "POST", "/values:batchUpdate", body={"valueInputOption": "RAW", "data": ranges}, retry=False
        )

    def append_rows(self, range_name: str, rows: list[list]):
        # Public primitive: storage uses atomic appendCells groups rather than per-row calls.
        return self._request(
            "POST",
            f"/values/{quote(range_name, safe='')}:append",
            params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
            body={"values": rows},
            retry=False,
        )

    def find_by_id(self, tab: str, headers: list[str], id_column: str, oid: str):
        rows = self.read_range(f"'{tab}'!A1:{column_name(len(headers))}{self.config.sheets_max_rows + 1}")
        position = rows[0].index(id_column) if rows else -1
        for number, row in enumerate(rows[1:], 2):
            if position >= 0 and position < len(row) and row[position] == oid:
                return number, row
        return None

    def close(self):
        self.http.close()
