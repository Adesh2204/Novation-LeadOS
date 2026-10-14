import hashlib
import json
import logging
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from leados.config import ROOT, settings
from leados.engine import canonical_url

logger = logging.getLogger(__name__)

CACHE_LOCK = threading.Lock()
DEFAULT_CACHE_FILE = ROOT / "data/provider_cache.json"


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.strip().casefold().encode()).hexdigest()


class ProviderCache:
    """Thread-safe persistent cache for Exa queries and Firecrawl scraped pages.

    Enforces freshness TTLs and daily usage ceilings to protect API credits.
    """

    def __init__(self, cache_file: Path | None = None):
        self.cache_file = cache_file or DEFAULT_CACHE_FILE
        self._data: dict[str, Any] = {"searches": {}, "crawls": {}, "daily_usage": {}}
        self._load()

    def _load(self) -> None:
        if self.cache_file.exists():
            try:
                self._data = json.loads(self.cache_file.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Could not read provider cache file: %s; starting fresh.", exc)
                self._data = {"searches": {}, "crawls": {}, "daily_usage": {}}
        else:
            self._data = {"searches": {}, "crawls": {}, "daily_usage": {}}

    def _save(self) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            temp = self.cache_file.with_name(f"{self.cache_file.name}.tmp")
            temp.write_text(json.dumps(self._data, default=str), encoding="utf-8")
            temp.replace(self.cache_file)
        except Exception as exc:
            logger.warning("Failed to save provider cache to %s: %s", self.cache_file, exc)

    def get_search(self, query: str, ttl_hours: int | None = None) -> list[dict[str, Any]] | None:
        ttl = ttl_hours if ttl_hours is not None else settings.exa_search_cache_ttl_hours
        q_hash = _hash_key(query)
        with CACHE_LOCK:
            entry = self._data.get("searches", {}).get(q_hash)
            if not entry:
                return None
            try:
                saved_at = datetime.fromisoformat(entry["saved_at"])
                if datetime.now(UTC) - saved_at > timedelta(hours=ttl):
                    return None  # Expired
                return entry.get("results")
            except Exception:
                return None

    def set_search(self, query: str, results: list[dict[str, Any]]) -> None:
        q_hash = _hash_key(query)
        with CACHE_LOCK:
            if "searches" not in self._data:
                self._data["searches"] = {}
            self._data["searches"][q_hash] = {
                "query": query,
                "saved_at": datetime.now(UTC).isoformat(),
                "results": results,
            }
            self._save()

    def get_crawl(self, url: str, ttl_hours: int | None = None) -> dict[str, Any] | None:
        ttl = ttl_hours if ttl_hours is not None else settings.firecrawl_cache_ttl_hours
        clean_url = canonical_url(url)
        u_hash = _hash_key(clean_url)
        with CACHE_LOCK:
            entry = self._data.get("crawls", {}).get(u_hash)
            if not entry:
                return None
            try:
                saved_at = datetime.fromisoformat(entry["saved_at"])
                if datetime.now(UTC) - saved_at > timedelta(hours=ttl):
                    return None  # Expired
                return entry.get("document")
            except Exception:
                return None

    def set_crawl(self, url: str, document: dict[str, Any]) -> None:
        clean_url = canonical_url(url)
        u_hash = _hash_key(clean_url)
        with CACHE_LOCK:
            if "crawls" not in self._data:
                self._data["crawls"] = {}
            self._data["crawls"][u_hash] = {
                "url": clean_url,
                "saved_at": datetime.now(UTC).isoformat(),
                "document": document,
            }
            self._save()

    def _today_key(self) -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    def get_daily_usage(self, provider: str) -> int:
        today = self._today_key()
        with CACHE_LOCK:
            return self._data.get("daily_usage", {}).get(today, {}).get(provider, 0)

    def check_daily_budget(self, provider: str, max_calls: int) -> bool:
        return self.get_daily_usage(provider) < max_calls

    def record_call(self, provider: str) -> int:
        today = self._today_key()
        with CACHE_LOCK:
            if "daily_usage" not in self._data:
                self._data["daily_usage"] = {}
            if today not in self._data["daily_usage"]:
                self._data["daily_usage"][today] = {}
            current = self._data["daily_usage"][today].get(provider, 0) + 1
            self._data["daily_usage"][today][provider] = current
            self._save()
            return current

    def reserve_call(self, provider: str, max_calls: int) -> bool:
        """Check and reserve in one lock, including concurrent SDK worker threads."""
        today = self._today_key()
        with CACHE_LOCK:
            usage = self._data.setdefault("daily_usage", {}).setdefault(today, {})
            if usage.get(provider, 0) >= max_calls:
                return False
            usage[provider] = usage.get(provider, 0) + 1
            self._save()
            return True

    def record_call_result(self, provider: str, success: bool, error_msg: str | None = None) -> None:
        with CACHE_LOCK:
            if "health" not in self._data:
                self._data["health"] = {}
            if provider not in self._data["health"]:
                self._data["health"][provider] = {}
            now = datetime.now(UTC).isoformat()
            if success:
                self._data["health"][provider]["last_success"] = now
                self._data["health"][provider]["last_error"] = None
            else:
                self._data["health"][provider]["last_error"] = error_msg or "Unknown error"
                self._data["health"][provider]["last_error_at"] = now
            self._save()

    def get_stats(self) -> dict[str, Any]:
        today = self._today_key()
        with CACHE_LOCK:
            usage = self._data.get("daily_usage", {}).get(today, {})
            health = self._data.get("health", {})
            return {
                "daily_exa_calls": usage.get("exa", 0),
                "daily_firecrawl_calls": usage.get("firecrawl", 0),
                "last_exa_success": health.get("exa", {}).get("last_success"),
                "last_exa_error": health.get("exa", {}).get("last_error"),
                "last_firecrawl_success": health.get("firecrawl", {}).get("last_success"),
                "last_firecrawl_error": health.get("firecrawl", {}).get("last_error"),
                "cached_searches_count": len(self._data.get("searches", {})),
                "cached_crawls_count": len(self._data.get("crawls", {})),
            }

    def clear(self) -> None:
        with CACHE_LOCK:
            self._data = {"searches": {}, "crawls": {}, "daily_usage": {}, "health": {}}
            self._save()


# Singleton application instance
provider_cache = ProviderCache()
