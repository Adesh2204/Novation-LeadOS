"""Stop future discovery requests; in-flight requests finish within their timeout."""

from pathlib import Path

from leados.config import ROOT, settings

path = Path(settings.discovery_jobs_path)
path.mkdir(parents=True, exist_ok=True)
(path / "STOP_LIVE_DISCOVERY").touch()
p = ROOT / ".env"
lines = p.read_text().splitlines()
lines = [
    "LIVE_DISCOVERY_ENABLED=false"
    if line.startswith("LIVE_DISCOVERY_ENABLED=")
    else line
    for line in lines
]
if not any(line.startswith("LIVE_DISCOVERY_ENABLED=") for line in lines):
    lines.append("LIVE_DISCOVERY_ENABLED=false")
p.write_text("\n".join(lines) + "\n")
print(
    "Live discovery disabled. Stop flag set. In-flight calls may finish; no further discovery requests will start."
)
