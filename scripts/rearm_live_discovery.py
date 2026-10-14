"""Explicitly authorised reactivation; startup never invokes this command."""

import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

from leados.config import ROOT, Settings
from leados.providers.cache import DEFAULT_CACHE_FILE, ProviderCache
from leados.services.live_activation import live_readiness
from leados.storage.factory import build_storage


def active_jobs(path: Path) -> list[str]:
    return [
        file.stem
        for file in path.glob("job_*.json")
        if json.loads(file.read_text())["status"] in {"QUEUED", "RUNNING", "SYNCING"}
    ]


def persist_activation(env: Path):
    changes = {
        "LIVE_DISCOVERY_ENABLED": "true",
        "LIVE_PROVIDER_DRY_RUN": "false",
        "ENABLE_EMAIL_SEND": "false",
    }
    lines = env.read_text().splitlines()
    seen = set()
    for i, line in enumerate(lines):
        key = line.partition("=")[0]
        if key in changes:
            lines[i] = f"{key}={changes[key]}"
            seen.add(key)
    lines.extend(f"{key}={value}" for key, value in changes.items() if key not in seen)
    temporary = env.with_suffix(".activation.pending")
    temporary.write_text("\n".join(lines) + "\n")
    temporary.chmod(0o600)
    os.replace(temporary, env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--enable", action="store_true")
    args = parser.parse_args()
    config = Settings()
    path = Path(config.discovery_jobs_path)
    # Refuse unreadable ledgers rather than accidentally treating lost history as zero use.
    ledger = DEFAULT_CACHE_FILE.read_bytes()
    json.loads(ledger)
    digest = hashlib.sha256(ledger).hexdigest()
    status = live_readiness(
        config.model_copy(update={"live_discovery_enabled": True}), ProviderCache()
    )
    blockers = [b for b in status["blockers"] if not b.startswith("Emergency stop")]
    jobs = active_jobs(path)
    if jobs:
        blockers.append("An active discovery job must finish before reactivation")
    storage = build_storage(config)
    with storage.transaction(refresh=True):
        health = storage.health()
    if (
        config.leados_storage != "google_sheets"
        or not health.get("connected")
        or not health.get("rows_valid")
        or health.get("pending_write")
    ):
        blockers.append(
            "Google Sheets must be connected, valid and have no pending transaction"
        )
    output = {
        "checks_passed": not blockers,
        "blockers": blockers,
        "active_jobs": jobs,
        "google_sheets_connected": health.get("connected", False),
        "ledger_sha256": digest,
        "remaining_daily_reservations": status["remaining_daily_reservations"],
        "stop_active": status["stop_active"],
    }
    if args.enable and not blockers:
        if DEFAULT_CACHE_FILE.read_bytes() != ledger:
            raise RuntimeError(
                "Usage changed during preflight; retry checks before rearming"
            )
        marker = path / "STOP_LIVE_DISCOVERY"
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        archive = path / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        env = ROOT / ".env"
        backup = archive / f"settings-{stamp}.env.backup"
        backup.write_bytes(env.read_bytes())
        backup.chmod(0o600)
        persist_activation(env)
        if marker.exists():
            marker.rename(archive / f"STOP_LIVE_DISCOVERY-{stamp}")
        current = Settings()
        if not current.live_discovery_enabled or marker.exists():
            raise RuntimeError("Persistent activation could not be verified")
        output["enabled"] = True
        output["stop_active"] = marker.exists()
        output["ready"] = live_readiness(current, ProviderCache())["ready"]
        # A healthy local dev supervisor reloads source safely; never kill unknown listeners.
        process_list = subprocess.check_output(["ps", "-axo", "command="], text=True)
        if "uvicorn leados.api:app" in process_list and "--reload" in process_list:
            (ROOT / "backend/leados/api.py").touch()
            output["backend_reloaded"] = False
            for _ in range(30):
                time.sleep(1)
                try:
                    with urlopen(
                        "http://127.0.0.1:8000/pipeline/discover/live/status", timeout=2
                    ) as response:
                        runtime = json.load(response)
                    if runtime.get("ready"):
                        output["backend_reloaded"] = True
                        break
                except (OSError, ValueError):
                    continue
            if not output["backend_reloaded"]:
                output["action_required"] = (
                    "Restart the backend to load persisted configuration; runtime is not verified ready"
                )
        else:
            output["action_required"] = "Run make dev to load the enabled configuration"
        output["usage_preserved"] = DEFAULT_CACHE_FILE.read_bytes() == ledger
    print(json.dumps(output, indent=2))
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
