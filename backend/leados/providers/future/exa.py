import asyncio
import json
import os
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx
from exa_py import Exa
from exa_py.api import ExaJSONEncoder
from pydantic import ValidationError

from leados.config import settings
from leados.providers.base import ProviderError
from leados.providers.cache import provider_cache
from leados.providers.control import assert_running
from leados.providers.http import safe_error
from leados.schemas import MarketDocument


class TimedExa(Exa):
    """Bound the SDK's search HTTP call as well as its async worker timeout."""

    def request(self, endpoint, data=None, method="POST", params=None, headers=None):
        if endpoint != "/search":
            return super().request(endpoint, data, method, params, headers)
        response = httpx.request(
            method,
            self.base_url + endpoint,
            content=json.dumps(data, cls=ExaJSONEncoder),
            params=params,
            headers={**self.headers, **(headers or {})},
            timeout=settings.exa_timeout_seconds,
        )
        response.raise_for_status()
        return response.json()


class ExaSearchProvider:
    """Canonical Exa API provider for discovering real-time company events,

    executive hiring, and business signals for lead generation.
    Adheres strictly to the official build-with-exa skill specifications:
    - Default retrieval: type="auto", contents={"highlights": True}
    - Structured extraction: compact outputSchema and verification systemPrompt
    - Deep research: Exa Agent API (/agent/runs) with explicit effort and polling
    """

    name: str = "exa_search"
    model: str = "auto"

    def __init__(
        self,
        api_key: str | None = None,
        enabled: bool | None = None,
        num_results: int | None = None,
    ):
        self.api_key = (
            api_key if api_key is not None else (settings.exa_api_key or os.getenv("EXA_API_KEY", ""))
        )
        # Enable explicitly or when search_provider is configured as exa with a valid key
        self.enabled = (
            enabled if enabled is not None else (settings.search_provider == "exa" and bool(self.api_key))
        )
        self.num_results = num_results
        self._client: Exa | None = None
        self.actual_requests = 0
        self.should_stop: Callable[[], bool] | None = None

    def _get_client(self) -> Exa:
        if not self.enabled:
            raise ProviderError("future_adapter_disabled")
        if not self.api_key:
            raise ProviderError("missing_exa_api_key")
        if self._client is None:
            self._client = TimedExa(api_key=self.api_key)
        return self._client

    async def search(
        self, company: str | None = None, force_refresh: bool = False, query: str | None = None
    ) -> list[dict[str, Any]]:
        """Search Exa for real-time company events, executive hiring, and business signals."""
        if not self.enabled:
            raise ProviderError("future_adapter_disabled")
        return await asyncio.wait_for(
            asyncio.to_thread(self._sync_search, company, force_refresh, query),
            timeout=settings.exa_timeout_seconds,
        )

    def _sync_search(
        self, company: str | None = None, force_refresh: bool = False, query: str | None = None
    ) -> list[dict[str, Any]]:
        assert_running(getattr(self, "should_stop", None))
        client = self._get_client()

        # Follow build-with-exa: natural language query encoding intent & recency
        if query:
            system_prompt = "Extract only company events directly supported by the returned sources. Include the exact supporting source_url for each event. Omit unknown details and rumors."
        elif company:
            clean_company = company.strip()
            query = f"recent executive hiring, leadership appointments, and business announcements for {clean_company}"
            system_prompt = (
                f"Extract verified executive appointments, leadership hiring, and corporate announcements for {clean_company}. "
                "Identify the company name, sector, country, person hired, role title, and event summary. "
                "Omit unverified rumors."
            )
        else:
            query = "recent executive hiring, leadership appointments, and business expansion announcements in India"
            system_prompt = (
                "Extract verified real-time executive appointments, leadership hiring, and business expansion in India. "
                "Identify the company name, sector, country, person hired, role title, and event summary. "
                "Omit unverified rumors."
            )

        # Check Exa search freshness cache (12-hour TTL) unless force_refresh is requested
        if not force_refresh:
            cached = provider_cache.get_search(query)
            if cached is not None:
                return cached

        # Check daily Exa call ceiling
        if not provider_cache.check_daily_budget("exa", settings.max_exa_calls_per_day):
            raise ProviderError("daily_exa_budget_exhausted")

        # Compact output schema adhering to Exa maximum property constraints (< 10 properties)
        schema = {
            "type": "object",
            "properties": {
                "events": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "company_name": {"type": "string"},
                            "sector": {"type": "string"},
                            "country": {"type": "string"},
                            "person_hired": {"type": "string"},
                            "role_title": {"type": "string"},
                            "event_summary": {"type": "string"},
                            "source_url": {"type": "string"},
                        },
                        "required": ["company_name", "event_summary", "source_url"],
                    },
                }
            },
            "required": ["events"],
        }

        search_kwargs: dict[str, Any] = {
            "query": query,
            "type": "auto",
            "contents": {"highlights": True},
            "system_prompt": system_prompt,
            "output_schema": schema,
        }
        if self.num_results is not None:
            search_kwargs["num_results"] = self.num_results

        if not provider_cache.reserve_call("exa", settings.max_exa_calls_per_day):
            raise ProviderError("daily_exa_budget_exhausted", retryable=False)
        try:
            self.actual_requests += 1
            res = client.search(**search_kwargs)
        except Exception as exc:
            error = safe_error(
                "exa",
                getattr(getattr(exc, "response", None), "status_code", getattr(exc, "status_code", None)),
            )
            provider_cache.record_call_result("exa", False, error.code)
            raise error from exc
        provider_cache.record_call_result("exa", True)
        documents = self._format_results_to_documents(res, fallback_company=company)
        provider_cache.set_search(query, documents)
        return documents

    def _format_results_to_documents(
        self, res: Any, fallback_company: str | None = None
    ) -> list[dict[str, Any]]:
        results = getattr(res, "results", []) or []
        output = getattr(getattr(res, "output", None), "content", None)
        events = output.get("events", []) if isinstance(output, dict) else []
        documents = []
        for source in results:
            url = getattr(source, "url", "")
            title = getattr(source, "title", "") or "Source announcement"
            source_text = " ".join(getattr(source, "highlights", []) or []) or title
            event: dict[str, Any] | None = next((row for row in events if row.get("source_url") == url), None)
            event = event or {}
            name = event.get("company_name") or fallback_company or self._infer_company_name(title)
            if not name or not url:
                continue
            # Preserve the actual retrieved excerpt; extracted summaries are not quoted facts.
            matched = name.casefold() in (title + " " + source_text).casefold()
            published = None
            raw_date = getattr(source, "published_date", None)
            if isinstance(raw_date, str):
                try:
                    published = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).date().isoformat()
                except ValueError:
                    pass  # An unknown event date must never become today's date.
            country, sector = event.get("country") or "Unknown", event.get("sector") or "Unknown"
            document = {
                "company": {
                    "name": name,
                    "aliases": [],
                    "domain": self._extract_domain(url, name),
                    "country": country,
                    "sector": sector,
                    "employee_range": "Unknown",
                    "funding_stage": "Unknown",
                    "locations": [] if country == "Unknown" else [country],
                    "description": event.get("event_summary") or title,
                },
                "source_url": url,
                "source_name": title,
                "source_type": self._source_type(url, title, source_text),
                "published_date": published,
                "snippet": source_text[:12000],
                "confidence": (0.85 if self._extract_domain(url, name) else 0.65) if matched else 0.4,
                "assertion_type": "FACT",
                "company_match": matched,
                "conflict": False,
                "author": getattr(source, "author", None),
                "jurisdiction": None if country == "Unknown" else country,
                "language": "en",
                "title": title,
                "record_origin": "LIVE",
                "provider_score": getattr(source, "score", None)
                if isinstance(getattr(source, "score", None), (int, float))
                else None,
                "provenance": {
                    "provider": "exa",
                    "source_url": url,
                    "excerpt_kind": "highlights",
                    "structured_event": bool(event),
                },
            }
            try:
                documents.append(MarketDocument.model_validate(document).model_dump(mode="json"))
            except ValidationError:
                continue
        return documents

    @staticmethod
    def _source_type(url: str, title: str, text: str) -> str:
        value = (url + " " + title + " " + text[:2000]).casefold()
        if any(word in value for word in ["rfp", "tender", "request for proposal", "procurement"]):
            return "procurement_notice"
        if any(word in value for word in ["/jobs", "/careers", "hiring", "vacancy"]):
            return "job_posting"
        if any(word in value for word in ["brand-post", "prnewswire", "press-release"]):
            return "press_release"
        return "reporting"

    def _infer_company_name(self, title: str) -> str:
        cleaned = re.split(r"[-|:–—]", title)[0].strip()
        for keyword in [
            " appoints",
            " names",
            " hires",
            " welcomes",
            " promotes",
            " launches",
            " announces",
            " expands",
            " recruits",
        ]:
            index = cleaned.casefold().find(keyword)
            if index > 0:
                return cleaned[:index].strip()
        return " ".join(cleaned.split()[:4]) or "Discovered Enterprise"

    def _extract_domain(self, url: str, company_name: str) -> str | None:
        try:
            from urllib.parse import urlparse

            netloc = urlparse(url).netloc
            # If news domain, do not assign to company
            news_domains = {
                "thehindubusinessline.com",
                "economictimes.indiatimes.com",
                "livemint.com",
                "reuters.com",
                "bloomberg.com",
                "exchange4media.com",
                "techcrunch.com",
            }
            if netloc.lower().replace("www.", "") in news_domains:
                return None
            domain = netloc.lower().replace("www.", "")
            tokens = [
                token
                for token in re.findall(r"[a-z0-9]+", company_name.casefold())
                if len(token) >= 4
                and token
                not in {"limited", "private", "corporation", "technologies", "technology", "systems"}
            ]
            return domain if any(token in domain.split(".")[0] for token in tokens) else None
        except Exception:
            return None

    async def research_agent(
        self,
        query: str,
        effort: str = "auto",
        output_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Deep multi-step executive hiring research and enrichment via Exa Agent API (/agent/runs)."""
        if not self.enabled:
            raise ProviderError("future_adapter_disabled")
        return await asyncio.to_thread(self._sync_research_agent, query, effort, output_schema)

    def _sync_research_agent(
        self,
        query: str,
        effort: str = "auto",
        output_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = self._get_client()

        agent_kwargs: dict[str, Any] = {
            "query": query,
            "effort": effort,
        }
        if output_schema is not None:
            agent_kwargs["output_schema"] = output_schema

        try:
            run = client.agent.runs.create(**agent_kwargs)
            finished = client.agent.runs.poll_until_finished(run.id, poll_interval=4000)

            if finished.status == "completed":
                return {
                    "run_id": run.id,
                    "status": "completed",
                    "text": getattr(finished.output, "text", None),
                    "structured": getattr(finished.output, "structured", None),
                    "grounding": getattr(finished.output, "grounding", None),
                    "cost_dollars": getattr(finished, "cost_dollars", None),
                }
            return {
                "run_id": run.id,
                "status": finished.status,
                "error": "exa_agent_incomplete",
            }
        except Exception as exc:
            raise safe_error("exa_agent", getattr(exc, "status_code", None)) from exc
