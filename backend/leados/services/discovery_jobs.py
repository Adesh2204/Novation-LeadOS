"""Persisted progress with one background writer; dashboard reads remain independent."""

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from leados.config import settings
from leados.schemas import LiveDiscoveryInput
from leados.services.live_discovery import LiveDiscoveryService, LiveDiscoverySummary
from leados.services.master_view_sync import application_storage
from leados.storage.base import StorageError, StorageProvider
from leados.storage.factory import api_write_lock, runtime_storage
from leados.storage.master_view_writer import atomic_json

logger = logging.getLogger(__name__)
ACTIVE = {"QUEUED", "RUNNING", "SYNCING"}


class DiscoveryJobs:
    def __init__(self, path: Path | None = None):
        self.path = path or Path(settings.discovery_jobs_path)
        self.jobs: dict[str, dict] = {}
        self.tasks: set[asyncio.Task] = set()
        if self.path.exists():
            for file in self.path.glob("job_*.json"):
                try:
                    job = json.loads(file.read_text())
                    if job["status"] in ACTIVE:
                        job.update(status="FAILED", stage="interrupted", error="server_restarted")
                        atomic_json(file, job)
                    self.jobs[job["job_id"]] = job
                except (OSError, ValueError, KeyError):
                    logger.warning("Ignoring invalid discovery progress record")

    def save(self, job: dict):
        atomic_json(self.path / f"{job['job_id']}.json", job)
        self.jobs[job["job_id"]] = job

    def stop(self, job_id: str):
        job = self.jobs.get(job_id)
        if not job:
            raise StorageError("discovery_job_not_found")
        stopped = {**job, "stop_requested": True, "updated_at": datetime.now(UTC).isoformat()}
        self.save(stopped)
        return stopped

    def latest(self):
        return max(self.jobs.values(), key=lambda job: job["created_at"], default=None)

    def start(self, body: LiveDiscoveryInput, storage: StorageProvider | None = None):
        for job in self.jobs.values():
            if job["status"] in ACTIVE:
                return job  # Double-click/reconnect attaches to the existing run without spending twice.
        job = {
            "job_id": "job_" + str(uuid4()),
            "status": "QUEUED",
            "stage": "queued",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "request": body.model_dump(mode="json"),
            "summary": None,
            "error": None,
            "sheets_synced": False,
        }
        self.save(job)
        task = asyncio.create_task(self._run(job, storage))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return job

    async def _run(self, job: dict, storage: StorageProvider | None):
        async with api_write_lock:
            await asyncio.to_thread(self._execute, job, storage or runtime_storage())

    def _execute(self, job: dict, storage: StorageProvider):
        body = LiveDiscoveryInput.model_validate(job["request"])

        def progress(summary: LiveDiscoverySummary):
            updated = {
                **self.jobs[job["job_id"]],
                "status": "RUNNING",
                "stage": summary.stage,
                "summary": summary.model_dump(mode="json"),
                "updated_at": datetime.now(UTC).isoformat(),
            }
            self.save(updated)

        try:
            outcome: dict = {}
            self.save({**job, "status": "RUNNING", "stage": "loading"})
            with application_storage(storage, refresh=True, outcome=outcome):
                summary = asyncio.run(
                    LiveDiscoveryService(storage).run(
                        verticals=body.verticals,
                        max_queries=body.max_queries,
                        dry_run=body.dry_run,
                        cache_only=body.cache_only,
                        company_filter=body.company,
                        max_companies=body.max_companies,
                        progress=progress,
                        query_offset=body.query_offset,
                        should_stop=lambda: (
                            self.jobs[job["job_id"]].get("stop_requested", False)
                            or (self.path / "STOP_LIVE_DISCOVERY").exists()
                        ),
                    )
                )
                self.save(
                    {
                        **self.jobs[job["job_id"]],
                        "status": "SYNCING",
                        "stage": "saving",
                        "summary": summary.model_dump(mode="json"),
                    }
                )
            current = self.jobs[job["job_id"]]
            pending = outcome.get("pending", False)
            self.save(
                {
                    **current,
                    "status": "PARTIAL" if pending and summary.status == "COMPLETED" else summary.status,
                    "stage": "complete",
                    "summary": summary.model_dump(mode="json"),
                    "error": "sheets_projection_pending" if pending else summary.error,
                    "sheets_synced": not pending,
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
        except Exception as error:
            code = error.code if isinstance(error, StorageError) else "discovery_job_failed"
            logger.warning("Discovery job failed: %s", code)
            self.save({**self.jobs[job["job_id"]], "status": "FAILED", "stage": "failed", "error": code})


discovery_jobs = DiscoveryJobs()
