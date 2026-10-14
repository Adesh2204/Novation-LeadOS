"""Non-destructive workbook migration with technical preflight before layout edits."""

from leados.config import Settings
from leados.services.master_view import MasterViewService
from leados.services.master_view_sync import sync_master_view, writer_for
from leados.storage.base import StorageError
from leados.storage.google_sheets import GoogleSheetsStorageProvider
from leados.storage.setup import initialize_workbook
from leados.storage.workbook import SCHEMAS, WORKBOOK_NAME, column_name


def setup_master_workbook(client, config: Settings) -> dict:
    metadata = client.metadata()
    if metadata["properties"]["title"] != WORKBOOK_NAME:
        raise StorageError("wrong_workbook_title", WORKBOOK_NAME)
    existing = {s["properties"]["title"]: s["properties"] for s in metadata["sheets"]}
    known = [t for t in SCHEMAS if t in existing]
    headers = (
        client.batch_read(
            [f"'{tab}'!A1:{column_name(existing[tab]['gridProperties']['columnCount'])}1" for tab in known]
        )
        if known
        else []
    )
    for tab, rows in zip(known, headers, strict=True):
        SCHEMAS[tab].validate_headers(rows[0] if rows else [])
    created = []
    if set(SCHEMAS) - set(existing):
        created = initialize_workbook(client, max_rows=config.sheets_max_rows)["created_tabs"]
    storage = GoogleSheetsStorageProvider(client, config)
    # Validate all populated technical data before changing master structure or visibility.
    with storage.transaction(refresh=True):
        MasterViewService(storage).build_rows()
        layout = writer_for(storage).initialize()
    result = sync_master_view(storage)
    return {
        "workbook": WORKBOOK_NAME,
        "technical_tabs_created": created,
        "technical_data_deleted": False,
        "master_layout": layout,
        "master_view": result,
    }
