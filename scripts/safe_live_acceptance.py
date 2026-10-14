"""Explicitly armed, capped acceptance. Persistent reservations prevent reruns overspending."""

import argparse
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from leados.config import settings
from leados.providers.cache import provider_cache
from leados.schemas import LiveDiscoveryInput
from leados.services.discovery_jobs import DiscoveryJobs
from leados.storage.factory import build_storage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Required to allow actual vendor requests",
    )
    parser.add_argument(
        "--repeat-cached", action="store_true", help="Allow cache only; no new requests"
    )
    args = parser.parse_args()
    if not args.execute:
        print(
            json.dumps(
                {
                    "mode": "OFFLINE_ESTIMATE",
                    "max_actual_exa_requests": 2,
                    "max_actual_firecrawl_requests": 3,
                    "max_deep_companies": 2,
                    "no_provider_requests": True,
                }
            )
        )
        return
    path = Path("data/archives/production-repair-20261009")
    path.mkdir(parents=True, exist_ok=True)
    ledger_path = path / "acceptance-usage.json"
    ledger = (
        json.loads(ledger_path.read_text())
        if ledger_path.exists()
        else {"exa": 0, "firecrawl": 0, "runs": []}
    )
    lock = threading.Lock()
    reserve = provider_cache.reserve_call

    def capped(provider, daily_limit):
        with lock:
            if args.repeat_cached or ledger.get(provider, 0) >= {
                "exa": 2,
                "firecrawl": 3,
            }.get(provider, 0):
                return False
            if not reserve(provider, daily_limit):
                return False
            ledger[provider] += 1
            ledger_path.write_text(json.dumps(ledger, indent=2))
            return True

    provider_cache.reserve_call = capped
    # Only this process is armed; the website remains disabled during controlled acceptance.
    settings.live_discovery_enabled = True
    settings.max_exa_searches_per_run = 2
    settings.max_exa_results_per_query = 5
    settings.max_firecrawl_companies_per_run = 2
    settings.max_firecrawl_pages_per_company = 2
    settings.max_firecrawl_pages_per_run = 3
    settings.enable_email_send = False
    stop = Path(settings.discovery_jobs_path) / "STOP_LIVE_DISCOVERY"
    if stop.exists():
        raise SystemExit(
            "Discovery stop flag is present. Remove it explicitly only when ready for this capped acceptance."
        )
    manager = DiscoveryJobs()
    at = datetime.now(UTC).isoformat()
    job = {
        "job_id": "job_" + str(uuid4()),
        "status": "QUEUED",
        "stage": "queued",
        "created_at": at,
        "updated_at": at,
        "request": LiveDiscoveryInput(
            max_queries=2, max_companies=2, dry_run=False, query_offset=0
        ).model_dump(mode="json"),
        "summary": None,
        "error": None,
        "sheets_synced": False,
    }
    manager.save(job)
    manager._execute(job, build_storage(settings))
    final = manager.jobs[job["job_id"]]
    ledger["runs"].append(
        {
            "job_id": job["job_id"],
            "status": final["status"],
            "sheets_synced": final["sheets_synced"],
            "summary": final.get("summary"),
            "repeat_cached": args.repeat_cached,
        }
    )
    ledger_path.write_text(json.dumps(ledger, indent=2))
    print(
        json.dumps(
            {
                "job_id": job["job_id"],
                "status": final["status"],
                "sheets_synced": final["sheets_synced"],
                "actual_request_reservations": {
                    "exa": ledger["exa"],
                    "firecrawl": ledger["firecrawl"],
                },
                "summary": final.get("summary"),
            },
            indent=2,
        )
    )
    if final["status"] == "FAILED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
