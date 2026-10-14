"""Secret-free manual discovery preflight; no provider requests or storage writes."""

from pathlib import Path

from leados.config import Settings
from leados.providers.cache import ProviderCache


def live_readiness(config: Settings, cache: ProviderCache) -> dict:
    stop = (Path(config.discovery_jobs_path) / "STOP_LIVE_DISCOVERY").exists()
    exa_remaining = max(0, config.max_exa_calls_per_day - cache.get_daily_usage("exa"))
    fire_remaining = max(0, config.max_firecrawl_calls_per_day - cache.get_daily_usage("firecrawl"))
    limits = {
        "queries": config.max_exa_searches_per_run,
        "results_per_query": config.max_exa_results_per_query,
        "companies": config.max_firecrawl_companies_per_run,
        "pages_per_company": config.max_firecrawl_pages_per_company,
        "pages": config.max_firecrawl_pages_per_run,
    }
    blockers = []
    if not config.live_discovery_enabled:
        blockers.append("Live discovery is disabled in configuration")
    if stop:
        blockers.append("Emergency stop is active; use the explicit rearm command after checking readiness")
    if not config.exa_api_key or not config.firecrawl_api_key:
        blockers.append("Exa and Firecrawl credentials are required")
    if config.live_research_mode not in {"EXA_FIRECRAWL", "FULL_LIVE"}:
        blockers.append("Exa + Firecrawl research mode is required")
    if min(limits.values()) < 1 or not exa_remaining or not fire_remaining:
        blockers.append("Provider request budget is unavailable")
    if config.enable_email_send:
        blockers.append("Email delivery must remain disabled for this research workflow")
    return {
        "enabled": config.live_discovery_enabled,
        "ready": not blockers,
        "stop_active": stop,
        "emergency_stop_available": True,
        "exa_configured": bool(config.exa_api_key),
        "firecrawl_configured": bool(config.firecrawl_api_key),
        "email_disabled": not config.enable_email_send,
        "remaining_daily_reservations": {"exa": exa_remaining, "firecrawl": fire_remaining},
        "limits": limits,
        "blockers": blockers,
    }
