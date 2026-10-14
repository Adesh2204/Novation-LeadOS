"""Start/reuse verified local services; never search, seed or clear a stop marker."""

import json
import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def listening(port):
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def read_json(url, timeout=5):
    with urlopen(url, timeout=timeout) as response:
        return json.load(response)


def healthy(port):
    url = f"http://127.0.0.1:{port}" + (
        "/health" if port == 8000 else "/api/backend/health"
    )
    try:
        result = read_json(url)
        return result.get("status") == "ok" and result.get("signals") == 114
    except (OSError, ValueError):
        return False


def main():
    children = []
    if (
        not (ROOT / ".venv/bin/uvicorn").is_file()
        or not shutil.which("npm")
        or not (ROOT / "frontend/node_modules/next").is_dir()
    ):
        print("Runtime dependencies are missing. Run make setup first.", flush=True)
        return 1
    commands = [
        (
            8000,
            [
                str(ROOT / ".venv/bin/uvicorn"),
                "leados.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
                "--reload",
            ],
            ROOT,
        ),
        (3000, ["npm", "run", "dev"], ROOT / "frontend"),
    ]
    try:
        for port, command, directory in commands:
            if listening(port):
                if not healthy(port):
                    raise RuntimeError(
                        f"Port {port} is occupied but LeadOS health is unavailable. Resolve that listener and retry."
                    )
                print(f"Reusing healthy LeadOS service on port {port}.", flush=True)
            else:
                children.append(
                    subprocess.Popen(command, cwd=directory, start_new_session=True)
                )
                deadline = time.monotonic() + 45
                while not healthy(port):
                    if time.monotonic() > deadline or any(
                        c.poll() is not None for c in children
                    ):
                        raise RuntimeError(
                            f"LeadOS on port {port} did not become healthy; inspect the startup error above."
                        )
                    time.sleep(0.5)
        storage = read_json("http://127.0.0.1:8000/storage/health", timeout=45)
        live = read_json("http://127.0.0.1:8000/pipeline/discover/live/status")
        sheets_ok = (
            storage.get("provider") == "google_sheets"
            and storage.get("connected")
            and storage.get("rows_valid")
            and not storage.get("pending_write")
        )
        print("\nNOVATION LEADOS\nBackend: RUNNING\nFrontend: RUNNING", flush=True)
        print(
            f"Google Sheets: {'CONNECTED' if sheets_ok else 'NEEDS ATTENTION'}",
            flush=True,
        )
        print(
            f"Exa: {'CONFIGURED' if live['exa_configured'] else 'MISSING'}\nFirecrawl: {'CONFIGURED' if live['firecrawl_configured'] else 'MISSING'}",
            flush=True,
        )
        print(
            f"Live Discovery: {'ENABLED' if live['ready'] else 'UNAVAILABLE'}\nEmail Sending: {'DISABLED' if live['email_disabled'] else 'ENABLED'}",
            flush=True,
        )
        print(
            "Dashboard: http://127.0.0.1:3000\nAPI: http://127.0.0.1:8000", flush=True
        )
        print(
            "READY FOR MANUAL LIVE DISCOVERY"
            if live["ready"] and sheets_ok
            else "Readiness: "
            + "; ".join(
                live["blockers"]
                + ([] if sheets_ok else ["Check Google Sheets storage"])
            ),
            flush=True,
        )
        while children:
            for child in children:
                if child.poll() is not None:
                    return child.returncode or 0
            time.sleep(0.25)
        return 0
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"Startup failed: {exc}", flush=True)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)


if __name__ == "__main__":
    raise SystemExit(main())
