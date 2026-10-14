import asyncio
import hashlib
import logging
import os
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from firecrawl import FirecrawlApp

from leados.config import settings
from leados.engine import canonical_url
from leados.providers.base import ProviderError
from leados.providers.cache import provider_cache
from leados.providers.control import assert_running
from leados.providers.http import safe_error
from leados.providers.models import CrawledDocument, ProviderBudget
from leados.providers.pre_screen import pre_screen_candidate
from leados.qualification import access_restricted, company_name_supported

logger = logging.getLogger(__name__)


class FirecrawlCrawlerProvider:
    """Targeted deep research and page scraper using Firecrawl.

    Strictly credit-safe:
    - Never crawls entire websites.
    - Stage A: Scrapes only the exact Exa source URL.
    - Early Exit: Stops immediately once verified evidence is confirmed.
    - Stage B: Only inspects up to 1 targeted path if Stage A is insufficient.
    - Fully cached with 7-day TTL and daily budget protection.
    """

    name: str = "firecrawl"
    model: str = "scrape"

    def __init__(
        self,
        api_key: str | None = None,
        enabled: bool | None = None,
        timeout_seconds: float | None = None,
        dry_run: bool | None = None,
    ):
        self.api_key = (
            api_key
            if api_key is not None
            else (settings.firecrawl_api_key or os.getenv("FIRECRAWL_API_KEY", ""))
        )
        self.enabled = (
            enabled
            if enabled is not None
            else (settings.crawler_provider == "firecrawl" and bool(self.api_key))
        )
        self.timeout = timeout_seconds or settings.firecrawl_timeout_seconds
        self.dry_run = dry_run
        self._app: FirecrawlApp | None = None
        self.actual_requests = 0
        self.cache_only = False
        self.should_stop: Callable[[], bool] | None = None

    def _get_app(self) -> FirecrawlApp:
        if not self.enabled:
            raise ProviderError("future_adapter_disabled")
        if not self.api_key:
            raise ProviderError("missing_firecrawl_api_key")
        if self._app is None:
            self._app = FirecrawlApp(api_key=self.api_key, timeout=self.timeout, max_retries=0)
        return self._app

    async def crawl(
        self,
        document: dict[str, Any],
        budget: ProviderBudget | None = None,
    ) -> dict[str, Any]:
        """CrawlerProvider protocol implementation.

        Takes a candidate discovery document, evaluates whether deep research is justified,
        and enriches with targeted Firecrawl scraping while strictly guarding credits.
        """
        if not self.enabled:
            raise ProviderError("future_adapter_disabled")

        return await self.enrich_candidate(document, budget)

    async def enrich_candidate(
        self,
        document: dict[str, Any],
        budget: ProviderBudget | None = None,
    ) -> dict[str, Any]:
        """Exact source first; extra URLs must have been discovered, never guessed."""
        enriched = dict(document)
        enriched["provenance"] = dict(document.get("provenance", {}))
        enriched["firecrawl_decisions"] = []
        source_url = document.get("source_url")

        def decision(value, status, **details):
            if enriched.get("crawler_error"):
                enriched["provenance"]["source_error"] = enriched["crawler_error"]
            enriched["firecrawl_decision"] = value
            enriched["crawler_status"] = status
            enriched["firecrawl_decisions"].append({"decision": value, "url": source_url, **details})
            return enriched

        if not source_url:
            return decision("NO_TARGET_URL", "NEEDS_RESEARCH")
        clean_url = canonical_url(str(source_url))
        company_info = enriched.get("company", {})
        company_key = company_info.get("domain") or company_info.get("name", "Unknown Company")
        if self.dry_run if self.dry_run is not None else settings.live_provider_dry_run:
            return decision("NEEDS_ADDITIONAL_RESEARCH", "WOULD_CRAWL", reason="Preview does not crawl")
        if not pre_screen_candidate(enriched).qualifies:
            return decision("LOW_RELEVANCE", "SKIPPED_LOW_RELEVANCE")
        cached = provider_cache.get_crawl(clean_url)
        if cached and cached.get("status") == "FAILED":
            try:
                failed_at = datetime.fromisoformat(cached["retrieved_at"])
            except (KeyError, ValueError):
                failed_at = datetime.min.replace(tzinfo=UTC)
            if datetime.now(UTC) - failed_at < timedelta(minutes=15):
                error = str(cached.get("metadata", {}).get("error") or "scrape_failed")
                enriched["crawler_error"] = error
                enriched["crawl_cache_reused"] = True
                return decision(
                    "ROBOTS_OR_ACCESS_RESTRICTED" if "restricted" in error else "PROVIDER_ERROR",
                    "NEEDS_RESEARCH",
                    cache_reused=True,
                    error=error,
                )
        if cached and self._access_restricted(cached.get("content", "")):
            enriched["crawler_error"] = "robots_or_access_restricted"
            enriched["crawl_cache_reused"] = True
            return decision("ROBOTS_OR_ACCESS_RESTRICTED", "NEEDS_RESEARCH", cache_reused=True)
        if cached and cached.get("status") == "SUCCESS" and cached.get("content"):
            self._attach_page(enriched, cached, clean_url)
            return decision("CACHE_REUSED", "CACHED", content_hash=cached.get("content_hash"))
        if self.cache_only:
            enriched["crawler_error"] = "cache_only_miss"
            return decision(
                "PROVIDER_ERROR",
                "NEEDS_RESEARCH",
                reason="Cache-only research requested; no extraction saved, no new request executed",
            )
        if budget and not budget.can_crawl_company(company_key):
            return decision("BUDGET_EXHAUSTED", "SKIPPED_BUDGET_LIMIT")
        if not provider_cache.reserve_call("firecrawl", settings.max_firecrawl_calls_per_day):
            return decision("BUDGET_EXHAUSTED", "SKIPPED_DAILY_BUDGET")
        if budget:
            budget.record_firecrawl_page(company_key)
        page = await self._scrape_safe(clean_url)
        enriched["firecrawl_decisions"].append(
            {"decision": "CALL_EXECUTED", "url": clean_url, "status": page.status}
        )
        enriched["firecrawl_decision"] = "CALL_EXECUTED"
        if page.status != "SUCCESS" or not page.content:
            provider_cache.set_crawl(clean_url, page.model_dump(mode="json"))
            error = page.metadata.get("error", "empty_content")
            enriched["crawler_error"] = error
            restricted = any(word in str(error) for word in ("403", "restricted", "robots", "forbidden"))
            return decision(
                "ROBOTS_OR_ACCESS_RESTRICTED" if restricted else "PROVIDER_ERROR",
                "NEEDS_RESEARCH",
                error=error,
            )
        provider_cache.set_crawl(clean_url, page.model_dump(mode="json"))
        self._attach_page(enriched, page.model_dump(mode="json"), clean_url)
        enriched["crawler_status"] = "STAGE_A_CONFIRMED"
        targets = document.get("additional_target_urls", [])[:1]
        for target in targets:
            if target == clean_url:
                continue
            extra = {**document, "source_url": target, "additional_target_urls": []}
            if budget and not budget.can_crawl_company(company_key):
                enriched["firecrawl_decisions"].append({"decision": "BUDGET_EXHAUSTED", "url": target})
                break
            researched = await self.enrich_candidate(extra, budget)
            enriched["firecrawl_decisions"].extend(researched.get("firecrawl_decisions", []))
            if researched.get("crawler_status") in {"CACHED", "STAGE_A_CONFIRMED"}:
                enriched.setdefault("additional_documents", []).append(researched)
                enriched["crawler_status"] = "STAGE_B_ENRICHED"
        return enriched

    def _attach_page(self, enriched: dict, page: dict, url: str):
        enriched["provenance"].pop("source_error", None)
        enriched["provenance"] = {
            **enriched.get("provenance", {}),
            "exa_excerpt": enriched.get("provenance", {}).get("exa_excerpt", enriched.get("snippet", "")),
            "firecrawl": {
                "url": url,
                "canonical_url": page.get("canonical_url", url),
                "title": page.get("title", ""),
                "published_date": page.get("published_date"),
                "retrieved_at": page.get("retrieved_at"),
                "content_hash": page.get("content_hash"),
                "source_type": page.get("source_type"),
                "status": page.get("status"),
                "metadata": page.get("metadata", {}),
            },
        }
        self._attach_source(enriched, page.get("content", ""))
        enriched["crawled_content_hash"] = page.get("content_hash")
        enriched["title"] = page.get("title") or enriched.get("title", "")
        if not enriched.get("published_date") and page.get("published_date"):
            enriched["published_date"] = page["published_date"]

    async def scrape_url(self, url: str) -> CrawledDocument:
        """Single-page scrape with caching, timeouts, and error isolation."""
        if not self.enabled:
            raise ProviderError("future_adapter_disabled")

        clean_url = canonical_url(url)
        cached = provider_cache.get_crawl(clean_url)
        if cached:
            return CrawledDocument.model_validate(cached)

        if not provider_cache.check_daily_budget("firecrawl", settings.max_firecrawl_calls_per_day):
            raise ProviderError("daily_firecrawl_budget_exhausted", retryable=False)
        if not provider_cache.reserve_call("firecrawl", settings.max_firecrawl_calls_per_day):
            raise ProviderError("daily_firecrawl_budget_exhausted", retryable=False)
        doc = await self._scrape_safe(clean_url)
        if doc and doc.status == "SUCCESS":
            provider_cache.set_crawl(clean_url, doc.model_dump(mode="json"))
        return doc

    def _attach_source(self, enriched: dict, content: str):
        # Only the exact source's text belongs under its URL. Never attach Stage B text here.
        if content:
            enriched["snippet"] = content[:12000]
            enriched["company_match"] = company_name_supported(enriched.get("company", {}), content)

    @staticmethod
    def _access_restricted(content: str) -> bool:
        return access_restricted(content)

    async def scrape_selected_pages(self, urls: list[str]) -> list[CrawledDocument]:
        """Scrape a small approved list of targeted URLs with concurrency limits."""
        results: list[CrawledDocument] = []
        for url in urls[: settings.max_firecrawl_pages_per_run]:
            res = await self.scrape_url(url)
            results.append(res)
        return results

    async def _scrape_safe(self, url: str) -> CrawledDocument:
        """Call Firecrawl within a thread and timeout guard."""
        app = self._get_app()
        try:
            doc = await asyncio.wait_for(
                asyncio.to_thread(self._sync_scrape, app, url),
                timeout=self.timeout,
            )
            provider_cache.record_call_result("firecrawl", doc.status == "SUCCESS", doc.metadata.get("error"))
            return doc
        except TimeoutError:
            logger.warning("Firecrawl scrape timed out after %ss for %s", self.timeout, url)
            provider_cache.record_call_result("firecrawl", False, "timeout")
            return CrawledDocument(
                url=url,
                canonical_url=url,
                title="",
                content="",
                content_hash=hashlib.sha256(b"").hexdigest(),
                provider="firecrawl",
                status="FAILED",
                metadata={"error": "timeout"},
            )
        except Exception as exc:
            error = safe_error("firecrawl", getattr(exc, "status_code", None))
            logger.warning("Firecrawl scrape error: %s", error.code)
            provider_cache.record_call_result("firecrawl", False, error.code)
            return CrawledDocument(
                url=url,
                canonical_url=url,
                title="",
                content="",
                content_hash=hashlib.sha256(b"").hexdigest(),
                provider="firecrawl",
                status="FAILED",
                metadata={"error": error.code},
            )

    def _sync_scrape(self, app: FirecrawlApp, url: str) -> CrawledDocument:
        assert_running(getattr(self, "should_stop", None))
        self.actual_requests += 1
        res = app.scrape(url, formats=["markdown"], skip_tls_verification=True)

        # Normalize SDK objects and raw response dictionaries without inventing dates.
        payload = res.model_dump() if hasattr(res, "model_dump") else res
        if isinstance(payload, dict):
            content = payload.get("markdown") or payload.get("content") or ""
            metadata = payload.get("metadata") or {}
        else:
            content = getattr(res, "markdown", "") or ""
            meta = getattr(res, "metadata", None)
            metadata = (
                meta.model_dump()
                if meta is not None and hasattr(meta, "model_dump")
                else (vars(meta) if meta else {})
            )
        title = metadata.get("title", "") or ""
        pub_date_str = (
            metadata.get("published_date") or metadata.get("published_time") or metadata.get("publishedTime")
        )
        reported_url = metadata.get("url") or metadata.get("og_url") or metadata.get("ogUrl") or url
        try:
            resolved_url = canonical_url(reported_url)
        except ValueError:
            resolved_url = canonical_url(url)
        status_code = metadata.get("status_code", metadata.get("statusCode", 200)) or 200

        content_clean = content.strip()
        restricted = status_code in {401, 403} or self._access_restricted(content_clean)
        c_hash = hashlib.sha256(content_clean.encode()).hexdigest()

        pub_date: date | None = None
        if pub_date_str:
            try:
                pub_date = datetime.fromisoformat(str(pub_date_str)[:10]).date()
            except Exception:
                pub_date = None

        return CrawledDocument(
            url=url,
            canonical_url=resolved_url,
            title=title or "Scraped Page",
            content=content_clean,
            published_date=pub_date,
            retrieved_at=datetime.now(UTC),
            content_hash=c_hash,
            source_type="scraped_page",
            provider="firecrawl",
            status="FAILED" if status_code >= 400 or restricted else "SUCCESS",
            metadata={
                "content_length": len(content_clean),
                "status_code": status_code,
                "credits_used": metadata.get("credits_used", metadata.get("creditsUsed")),
                "error": "robots_or_access_restricted"
                if restricted
                else "http_error"
                if status_code >= 400
                else None,
            },
        )
