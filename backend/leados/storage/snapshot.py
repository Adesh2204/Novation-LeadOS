"""A read-only, isolated view of the last committed storage revision."""

from leados.storage.base import StorageError, StorageProvider
from leados.storage.records import RECORD_TYPES


class SnapshotStorageProvider(StorageProvider):
    def __init__(self, baseline: dict, name: str, quarantined: set[str]):
        super().__init__()
        self.name = name
        self._records = {
            entity: {
                oid: RECORD_TYPES[entity].model_validate(row)
                for oid, row in rows.items()
                if oid not in quarantined
            }
            for entity, rows in baseline.items()
        }
        self._baseline = baseline
        self._loaded = True
        self.quarantined_ids = set(quarantined)

    def _load(self):
        return self._records

    def _persist(self, changes):
        raise StorageError("read_only_snapshot")

    def add(self, record):
        raise StorageError("read_only_snapshot")
