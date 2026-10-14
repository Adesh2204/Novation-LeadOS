"""Storage contract and provider-independent integrity rules."""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import threading
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar, cast

from leados.storage.records import (
    AuditLog,
    Company,
    CompanyAlias,
    CompanySignal,
    ContactEvent,
    DecisionMakerRole,
    FeedbackEvent,
    HumanReview,
    HumanReviewTask,
    Opportunity,
    OpportunityEvidence,
    OutreachDraft,
    ProviderRun,
    Record,
    ScoreComponent,
    Service,
    Signal,
    Source,
    SourceDocument,
    Suppression,
    SystemConfig,
    Vertical,
)

T = TypeVar("T", bound=Record)


class StorageError(Exception):
    """Only a safe category and non-sensitive structural detail may cross the API."""

    def __init__(self, code: str, detail: str = "", *, retryable: bool = False, retry_after: float = 0):
        self.code, self.detail, self.retryable = code, detail, retryable
        self.retry_after = retry_after
        super().__init__(code + (": " + detail if detail else ""))


UNIQUE: dict[type[Record], list[tuple[str, ...]]] = {
    Company: [("identity_key",)],
    CompanyAlias: [("company_id", "normalized_name", "country")],
    Source: [("origin",)],
    SourceDocument: [("url_hash",), ("content_hash",)],
    Signal: [("code",)],
    CompanySignal: [("company_id", "signal_id", "event_key")],
    Opportunity: [("opportunity_fingerprint",), ("company_signal_id", "vertical_id")],
    OpportunityEvidence: [("opportunity_id", "document_id")],
    ScoreComponent: [("opportunity_id", "name")],
    DecisionMakerRole: [("opportunity_id", "role")],
    OutreachDraft: [("opportunity_id",)],
    HumanReviewTask: [("opportunity_id",)],
    Suppression: [("company_id",)],
    SystemConfig: [("key",)],
}
REFERENCES: dict[type[Record], dict[str, type[Record]]] = {
    CompanyAlias: {"company_id": Company},
    SourceDocument: {"company_id": Company, "source_id": Source},
    CompanySignal: {"company_id": Company, "signal_id": Signal},
    Opportunity: {
        "company_id": Company,
        "company_signal_id": CompanySignal,
        "vertical_id": Vertical,
        "service_id": Service,
    },
    OpportunityEvidence: {"opportunity_id": Opportunity, "document_id": SourceDocument},
    ScoreComponent: {"opportunity_id": Opportunity},
    DecisionMakerRole: {"opportunity_id": Opportunity},
    OutreachDraft: {"opportunity_id": Opportunity},
    HumanReview: {"opportunity_id": Opportunity},
    HumanReviewTask: {"opportunity_id": Opportunity},
    FeedbackEvent: {"opportunity_id": Opportunity},
    Suppression: {"company_id": Company},
    ContactEvent: {"company_id": Company, "opportunity_id": Opportunity},
    Service: {"vertical_id": Vertical},
}
IMMUTABLE = {AuditLog, HumanReview, FeedbackEvent, ContactEvent}


def fingerprint(company_id: str, vertical_id: str, signal_id: str, event_bucket: str) -> str:
    return hashlib.sha256(json.dumps([company_id, vertical_id, signal_id, event_bucket]).encode()).hexdigest()


def normalize_run_history(history: Sequence[dict]) -> list[dict]:
    """Give older JSON snapshots stable UUIDs without changing logical run identities."""
    from uuid import NAMESPACE_URL, UUID, uuid5

    normalized = []
    for item in history:
        row = dict(item)
        snapshot_id = row.pop("snapshot_id", "") or "prs_" + str(
            uuid5(NAMESPACE_URL, json.dumps(row, sort_keys=True))
        )
        UUID(snapshot_id[-36:])
        record = ProviderRun.model_validate(row)
        normalized.append({**record.model_dump(mode="json"), "snapshot_id": snapshot_id})
    return normalized


class StorageProvider(ABC):
    """Typed CRUD, indexed lookups and a coordinated unit of work; no vendor methods."""

    name: str

    def __init__(self, lock_path: Path | None = None):
        self._records: dict[str, dict[str, Record]] = {}
        self._baseline: dict = {}
        self._indexes: dict = {}
        self._loaded = False
        self._depth = 0
        self._lock = threading.RLock()
        self.lock_path = lock_path
        self.metrics: Counter = Counter()
        self.validation_errors: list[dict] = []
        self.quarantined_ids: set[str] = set()
        self._pending_run_history: list[dict] = []
        self._read_view: StorageProvider | None = None
        self._read_baseline: dict | None = None
        self._published_baseline: dict = {}
        self._published_quarantined: set[str] = set()

    @abstractmethod
    def _load(self) -> dict[str, dict[str, Record]]: ...

    @abstractmethod
    def _persist(self, changes: list[Record]) -> None: ...

    def _ensure(self, refresh: bool = False):
        if self._loaded and not refresh:
            self.metrics["cache_hits"] += 1
            return
        self._records = self._load()
        self._loaded = True
        self._indexes.clear()
        # Definitions/services stay canonical in the repository, never manually in Sheets.
        from leados.knowledge import knowledge

        for v in knowledge.verticals.values():
            self._records.setdefault("Vertical", {})[v.id] = Vertical(
                id=v.id, version=v.version, definition=v.model_dump()
            )
            for i, service in enumerate(v.services):
                sid = f"{v.id}:{i}"
                self._records.setdefault("Service", {})[sid] = Service(id=sid, vertical_id=v.id, name=service)
        self._baseline = self.snapshot()
        self._validate_loaded()
        self._publish()

    def _publish(self):
        self._published_baseline = self._baseline
        self._published_quarantined = set(self.quarantined_ids)

    def _validate_loaded(self):
        return None

    def snapshot(self) -> dict:
        return {
            name: {oid: r.model_dump(mode="json") for oid, r in rows.items()}
            for name, rows in self._records.items()
        }

    def read_view(self) -> StorageProvider:
        """Publish only committed records, without taking a long-running writer lock."""
        from leados.storage.snapshot import SnapshotStorageProvider

        self._ensure()
        baseline = self._published_baseline
        if self._read_baseline is not baseline:
            self._read_view = SnapshotStorageProvider(baseline, self.name, self._published_quarantined)
            self._read_baseline = baseline
        assert self._read_view is not None
        return self._read_view

    def get(self, model: type[T], oid: str) -> T | None:
        self._ensure()
        self.metrics["reads"] += 1
        return self._records.get(model.__name__, {}).get(oid)  # type: ignore[return-value]

    def list(self, model: type[T], **filters) -> list[T]:
        self._ensure()
        self.metrics["reads"] += 1
        rows = self._records.get(model.__name__, {})
        if not filters:
            return cast(list[T], list(rows.values()))
        ids: list[str] | None = None
        for field, value in filters.items():
            key = (model.__name__, field)
            if key not in self._indexes:
                index: dict = {}
                for oid, row in rows.items():
                    index.setdefault(getattr(row, field), []).append(oid)
                self._indexes[key] = index
            else:
                self.metrics["cache_hits"] += 1
            matched = self._indexes[key].get(value, [])
            if ids is None:
                ids = list(matched)
            else:
                allowed = set(matched)
                ids = [oid for oid in ids if oid in allowed]
        return [rows[oid] for oid in ids or []]  # type: ignore[misc]

    def first(self, model: type[T], **filters) -> T | None:
        rows = self.list(model, **filters)
        return rows[0] if rows else None

    def add(self, record: T) -> T:
        self._ensure()
        rows = self._records.setdefault(type(record).__name__, {})
        if record.id in self.quarantined_ids:
            raise StorageError("quarantined_id", type(record).__name__)
        if record.id in rows and type(record) in IMMUTABLE:
            if rows[record.id] != record:
                raise StorageError("immutable_history", type(record).__name__)
            return record
        self._validate_record(record)
        for fields in UNIQUE.get(type(record), []):
            values = tuple(getattr(record, f) for f in fields)
            if any(v in {None, ""} for v in values):
                continue
            match = self.first(type(record), **dict(zip(fields, values, strict=True)))
            if match and match.id != record.id:
                self.metrics["duplicates_avoided"] += 1
                raise StorageError("duplicate_record", type(record).__name__)
        rows[record.id] = record
        self._indexes.clear()
        return record

    def _validate_record(self, record: Record):
        type(record).model_validate(record.model_dump())
        for field, target in REFERENCES.get(type(record), {}).items():
            if getattr(record, field) is None:
                continue
            if self.get(target, getattr(record, field)) is None:
                raise StorageError("missing_reference", f"{type(record).__name__}.{field}")
        if isinstance(record, SourceDocument):
            from leados.engine import canonical_url, digest

            if record.content_hash != digest(record.snippet.strip()) or record.url_hash != digest(
                canonical_url(record.source_url)
            ):
                raise StorageError("source_hash_mismatch", "SourceDocument")
        if isinstance(record, CompanySignal):
            if any(not self.get(SourceDocument, oid) for oid in record.evidence_ids):
                raise StorageError("missing_reference", "CompanySignal.evidence_ids")
        if isinstance(record, Opportunity):
            signal = self.get(CompanySignal, record.company_signal_id)
            if signal and signal.company_id != record.company_id:
                raise StorageError("company_mismatch", "Opportunity")
            expected = (
                fingerprint(record.company_id, record.vertical_id, signal.signal_id, signal.event_key)
                if signal
                else ""
            )
            if not record.opportunity_fingerprint:
                record.opportunity_fingerprint = expected
            if record.opportunity_fingerprint != expected:
                raise StorageError("invalid_fingerprint", "Opportunity")
            if record.audit_status != "VERIFIED" and record.score_band == "HOT":
                raise StorageError("unverified_hot", "Opportunity")
            links = self.list(OpportunityEvidence, opportunity_id=record.id)
            evidence_ids = (
                [link.document_id for link in links] if links else signal.evidence_ids if signal else []
            )
            for claim in [*record.facts, *record.allegations, *record.inferences]:
                if not claim["evidence_ids"] or not set(claim["evidence_ids"]).issubset(evidence_ids):
                    raise StorageError("invalid_claim_reference", "Opportunity")
                for oid in claim["evidence_ids"]:
                    document = self.get(SourceDocument, oid)
                    if (
                        claim["type"] in {"FACT", "ALLEGATION"}
                        and document
                        and document.assertion_type != claim["type"]
                    ):
                        raise StorageError("assertion_category_conflict", "Opportunity")
            if record.audit_status == "VERIFIED" and signal:
                from datetime import date

                from leados.engine import audit_evidence
                from leados.knowledge import knowledge
                from leados.pipeline import evidence_for

                status, _, _ = audit_evidence(
                    evidence_for(self, evidence_ids),
                    knowledge.signals[signal.signal_key],
                    date.today(),
                    record.inferences,
                    knowledge,
                    live=True,
                )
                if status != "VERIFIED":
                    raise StorageError("evidence_reverification_failed", "Opportunity")

    def update(self, model: type[T], oid: str, data: dict) -> T:
        record = self.get(model, oid)
        if record is None:
            raise StorageError("record_not_found", model.__name__)
        if model in IMMUTABLE:
            raise StorageError("immutable_history", model.__name__)
        if "id" in data or "created_at" in data:
            raise StorageError("immutable_identity", model.__name__)
        updated = model.model_validate({**record.model_dump(), **data})
        return self.add(updated)

    def flush(self):
        self._ensure()
        self._indexes.clear()
        changes = []
        for name, rows in self._records.items():
            for oid, record in rows.items():
                old = self._baseline.get(name, {}).get(oid)
                if record.id != oid or (
                    old and old["created_at"] != record.model_dump(mode="json")["created_at"]
                ):
                    raise StorageError("immutable_identity", name)
                if old == record.model_dump(mode="json"):
                    continue
                if type(record) in IMMUTABLE and old is not None:
                    raise StorageError("immutable_history", name)
                self._validate_record(record)
                changes.append(record)
        # Unit-of-work nesting accumulates one batch, never one write per object.
        if self._depth > 0:
            return
        if changes or self._pending_run_history:
            self._validate_scores()
            try:
                self._persist(changes)
            except Exception:
                self.metrics["failed_writes"] += len(changes)
                raise
            self.metrics["writes"] += len(changes)
            self.metrics["batch_writes"] += 1
            self._baseline = self.snapshot()
            self._publish()
            self._pending_run_history = []

    def _validate_scores(self):
        from leados.engine import score_band
        from leados.knowledge import knowledge

        for opportunity in self.list(Opportunity):
            parts = self.list(ScoreComponent, opportunity_id=opportunity.id)
            expected = knowledge.scoring["components"]
            if (
                {p.name: p.maximum for p in parts} != expected
                or any(not 0 <= p.points <= p.maximum for p in parts)
                or sum(p.points for p in parts) != opportunity.score
            ):
                raise StorageError("invalid_score_components", "Opportunity")
            band = (
                score_band(opportunity.score, knowledge.scoring)
                if opportunity.audit_status == "VERIFIED"
                else "IGNORE"
                if opportunity.audit_status == "REJECTED"
                else "MONITOR"
            )
            if opportunity.score_band != band:
                raise StorageError("invalid_score_band", "Opportunity")

    def commit(self):
        self.flush()

    def rollback(self):
        from leados.storage.records import RECORD_TYPES

        self._records = {
            name: {oid: RECORD_TYPES[name].model_validate(row) for oid, row in rows.items()}
            for name, rows in self._baseline.items()
        }
        self._indexes.clear()

    @contextmanager
    def transaction(self, *, refresh: bool = False):
        with self._lock:
            lock_file = None
            if self._depth == 0 and self.lock_path:
                self.lock_path.parent.mkdir(parents=True, exist_ok=True)
                lock_file = self.lock_path.open("a")
                fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                self._ensure(refresh=refresh and self._depth == 0)
                saved = copy.deepcopy(self._records)
                saved_history = copy.deepcopy(self._pending_run_history)
                self._depth += 1
                try:
                    yield self
                    if self._depth == 1:
                        self._depth = 0
                        try:
                            self.flush()
                        finally:
                            self._depth = 1
                except Exception:
                    self._records = saved
                    self._pending_run_history = saved_history
                    self._indexes.clear()
                    raise
                finally:
                    self._depth -= 1
            finally:
                if lock_file:
                    fcntl.flock(lock_file, fcntl.LOCK_UN)
                    lock_file.close()

    def begin_nested(self):
        return self.transaction()

    def import_run_history(self, history: Sequence[dict]):
        self._pending_run_history.extend(normalize_run_history(history))

    def health(self) -> dict:
        self._ensure()
        return {
            "provider": self.name,
            "connected": True,
            "spreadsheet_accessible": self.name == "google_sheets",
            "tabs_valid": True,
            "rows_valid": not self.validation_errors,
            "validation_errors": self.validation_errors,
            "metrics": {
                key: self.metrics[key]
                for key in [
                    "reads",
                    "writes",
                    "batch_reads",
                    "batch_writes",
                    "failed_writes",
                    "retries",
                    "cache_hits",
                    "duplicates_avoided",
                ]
            },
        }

    # Domain-facing operations; repositories build on these same generic primitives.
    def create_company(self, record: Company):
        return self.add(record)

    def update_company(self, oid: str, data: dict):
        return self.update(Company, oid, data)

    def get_company(self, oid: str):
        return self.get(Company, oid)

    def find_company(self, **filters):
        return self.first(Company, **filters)

    def list_companies(self, **filters):
        return self.list(Company, **filters)

    def create_signal(self, record: Signal):
        return self.add(record)

    def get_signal(self, oid: str):
        return self.get(Signal, oid)

    def list_signals(self, **filters):
        return self.list(Signal, **filters)

    def create_opportunity(self, record: Opportunity):
        return self.add(record)

    def update_opportunity(self, oid: str, data: dict):
        return self.update(Opportunity, oid, data)

    def get_opportunity(self, oid: str):
        return self.get(Opportunity, oid)

    def list_opportunities(self, **filters):
        return self.list(Opportunity, **filters)

    def store_evidence(self, record: OpportunityEvidence):
        return self.add(record)

    def list_evidence(self, oid: str):
        return self.list(OpportunityEvidence, opportunity_id=oid)

    def save_score_components(self, records: Sequence[ScoreComponent]):
        return [self.add(r) for r in records]

    def save_review(self, record: HumanReview):
        return self.add(record)

    def save_feedback(self, record: FeedbackEvent):
        return self.add(record)

    def save_outreach_draft(self, record: OutreachDraft):
        return self.add(record)

    def save_audit_event(self, record: AuditLog):
        return self.add(record)
