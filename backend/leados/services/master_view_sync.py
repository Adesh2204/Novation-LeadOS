"""Application-level post-commit projection orchestration and recoverable sync state."""

import hashlib
import json
import logging
from contextlib import contextmanager
from pathlib import Path
from weakref import WeakKeyDictionary

from leados.services.master_view import MasterViewService
from leados.storage.base import StorageError, StorageProvider
from leados.storage.google_sheets import GoogleSheetsStorageProvider
from leados.storage.master_view_writer import JsonMasterViewWriter, SheetsMasterViewWriter, atomic_json
from leados.storage.mock import MockStorageProvider

logger = logging.getLogger(__name__)
_writers: WeakKeyDictionary = WeakKeyDictionary()
_memory_state: WeakKeyDictionary = WeakKeyDictionary()


def writer_for(storage: StorageProvider):
    if storage not in _writers:
        if isinstance(storage, GoogleSheetsStorageProvider):
            _writers[storage] = SheetsMasterViewWriter(storage.client, storage.config)
        elif isinstance(storage, MockStorageProvider):
            path = storage.path.with_name(storage.path.stem + "-master-view.json") if storage.path else None
            _writers[storage] = JsonMasterViewWriter(path)
        else:
            raise StorageError("master_view_provider_unsupported", storage.name)
    return _writers[storage]


def state_path(storage: StorageProvider) -> Path | None:
    if isinstance(storage, GoogleSheetsStorageProvider):
        path = Path(storage.config.storage_outbox_path)
        return path.with_name(path.stem + "-master-view-status.json")
    if isinstance(storage, MockStorageProvider) and storage.path:
        return storage.path.with_name(storage.path.stem + "-master-view-status.json")
    return None


def sync_state(storage: StorageProvider) -> dict:
    path = state_path(storage)
    if path and path.exists():
        try:
            return json.loads(path.read_text())
        except (ValueError, OSError):
            return {"pending": True, "last_error": {"code": "master_view_state_invalid"}}
    return _memory_state.get(storage, {})


def save_state(storage: StorageProvider, state: dict):
    _memory_state[storage] = state
    path = state_path(storage)
    if path:
        atomic_json(path, state)


def sync_master_view(storage: StorageProvider) -> dict:
    """Read the latest committed domain state and sync only its derived presentation."""
    try:
        with storage.transaction(refresh=True):
            if isinstance(storage, GoogleSheetsStorageProvider) and storage.outbox.exists():
                raise StorageError("pending_storage_write", "Recover the technical storage outbox first")
            rows = MasterViewService(storage).build_rows()
            digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
            save_state(storage, {"pending": True, "projection_hash": digest})
            result = writer_for(storage).sync(rows)
            from leados.services.discovery_results import sync_discovery_results

            result.update(sync_discovery_results(storage))
            save_state(
                storage,
                {"pending": False, "projection_hash": digest, "last_synced_at": result["last_synced_at"]},
            )
            return {**result, "pending": False}
    except (StorageError, OSError, ValueError) as error:
        failure = error if isinstance(error, StorageError) else StorageError("master_view_io_failed")
        try:
            save_state(
                storage, {"pending": True, "last_error": {"code": failure.code, "message": failure.detail}}
            )
        except OSError:
            logger.warning("Unable to persist master-view retry marker")
        raise failure from None


def master_view_status(storage: StorageProvider) -> dict:
    with storage.transaction(refresh=True):
        rows = MasterViewService(storage).build_rows()
        result = writer_for(storage).status(rows)
        state = sync_state(storage)
        result.update(pending=state.get("pending", False))
        if state.get("last_error"):
            result["last_error"] = state["last_error"]
        result["valid"] = result["valid"] and not result["pending"]
        return result


@contextmanager
def application_storage(storage: StorageProvider, *, refresh=False, force_sync=False, outcome=None):
    """Keep projection work after the business commit, outside StorageProvider and engine."""
    with storage.transaction(refresh=refresh):
        before = MasterViewService(storage).fingerprint()
        yield storage
        changed = before != MasterViewService(storage).fingerprint()
    if force_sync or changed:
        try:
            result = sync_master_view(storage)
        except StorageError as error:
            logger.warning("Master view pending after successful domain commit: %s", error.code)
            result = {"pending": True, "error": {"code": error.code}}
        if outcome is not None:
            outcome.update(result)
