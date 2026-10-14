import asyncio
import json
from datetime import UTC, datetime

from leados.config import ROOT, settings
from leados.providers.base import ProviderError
from leados.providers.cache import provider_cache
from leados.providers.future.contacts import ContactOutContactProvider, SnovioContactProvider
from leados.providers.future.hubspot import HubSpotCRMProvider
from leados.providers.http import VendorHTTP
from leados.storage.factory import runtime_storage

STATUS_PATH = ROOT / "data/provider-connections.json"
check_lock = asyncio.Lock()


def connection_status() -> dict:
    try:
        checks = json.loads(STATUS_PATH.read_text())
    except (OSError, ValueError):
        checks = {}
    config = {
        "exa": ("Exa", bool(settings.exa_api_key)),
        "firecrawl": ("Firecrawl", bool(settings.firecrawl_api_key)),
        "openai": ("OpenAI", bool(settings.openai_api_key)),
        "contactout": ("ContactOut", bool(settings.contact_out_api_key)),
        "snovio": ("Snov.io", bool(settings.snovio_user_id and settings.snovio_secret)),
        "hubspot": ("HubSpot", bool(settings.hubspot_access_token)),
        "google_sheets": (
            "Google Sheets",
            settings.google_sheets_enabled and settings.leados_storage == "google_sheets",
        ),
    }
    providers = []
    stats = provider_cache.get_stats()
    for key, (label, configured) in config.items():
        previous = checks.get(key, {}) if configured else {}
        if key == "exa" and not previous and stats.get("last_exa_success"):
            previous = {"status": "connected", "checked_at": stats["last_exa_success"]}
        providers.append(
            {
                "id": key,
                "label": label,
                "configured": bool(configured),
                "status": previous.get("status", "configured" if configured else "missing"),
                "checked_at": previous.get("checked_at"),
                "error": previous.get("error"),
            }
        )
    providers += [
        {
            "id": "smtp",
            "label": "Email delivery",
            "configured": False,
            "status": "disabled",
            "optional": True,
        },
        {
            "id": "n8n",
            "label": "n8n scheduling",
            "configured": bool(settings.n8n_url),
            "status": "not_connected",
            "optional": True,
        },
    ]
    return {
        "providers": providers,
        "email_enabled": False,
        "mode": settings.live_research_mode,
        "live_discovery_enabled": settings.live_discovery_enabled,
        "dry_run": settings.live_provider_dry_run,
        "search": {
            "provider": "exa",
            "configured": bool(settings.exa_api_key),
            "enabled": settings.live_discovery_enabled,
        },
        "crawler": {
            "provider": "firecrawl",
            "configured": bool(settings.firecrawl_api_key),
            "enabled": settings.live_discovery_enabled,
        },
    }


async def check_connections() -> dict:
    async with check_lock:

        async def google_check():
            storage = runtime_storage()
            client = getattr(storage, "client", None)
            if client is None:
                raise ProviderError("google_sheets_not_configured", retryable=False)
            await asyncio.to_thread(client.metadata, fields="spreadsheetId")

        operations = {
            # Exa is verified by a bounded discovery request; status checks never spend search credits.
            "firecrawl": lambda: VendorHTTP(
                "firecrawl",
                "https://api.firecrawl.dev",
                {"Authorization": f"Bearer {settings.firecrawl_api_key}"},
            ).request("GET", "/v2/team/credit-usage"),
            "openai": lambda: VendorHTTP(
                "openai", "https://api.openai.com", {"Authorization": f"Bearer {settings.openai_api_key}"}
            ).request("GET", f"/v1/models/{settings.openai_model}"),
            "contactout": ContactOutContactProvider().check,
            "snovio": SnovioContactProvider().check,
            "hubspot": HubSpotCRMProvider().check,
            "google_sheets": google_check,
        }
        available = {row["id"] for row in connection_status()["providers"] if row["configured"]}

        async def check(name, operation):
            result = {"checked_at": datetime.now(UTC).isoformat()}
            try:
                await asyncio.wait_for(operation(), timeout=25)
                result["status"] = "connected"
            except Exception as error:
                result.update(
                    status="needs_attention",
                    error=error.code if isinstance(error, ProviderError) else f"{name}_unavailable",
                )
            return name, result

        results = await asyncio.gather(
            *(check(name, operation) for name, operation in operations.items() if name in available)
        )
        try:
            saved = json.loads(STATUS_PATH.read_text())
        except (OSError, ValueError):
            saved = {}
        saved.update(dict(results))
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = STATUS_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(saved))
        temporary.replace(STATUS_PATH)
        return connection_status()
