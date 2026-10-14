import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

import yaml
from pydantic import BaseModel, ConfigDict

from leados.config import ROOT, settings
from leados.engine import canonical_url, digest
from leados.pipeline import Pipeline
from leados.providers.base import ProviderError
from leados.providers.cache import provider_cache
from leados.providers.factory import get_providers
from leados.providers.future.exa import ExaSearchProvider
from leados.providers.future.firecrawl import FirecrawlCrawlerProvider
from leados.providers.models import ProviderBudget
from leados.providers.pre_screen import pre_screen_candidate
from leados.qualification import company_name_supported, qualify, source_sufficient
from leados.services.identity import company_dedup_key, document_heading
from leados.services.prospects import live_prospects
from leados.services.provenance import qualified_opportunity
from leados.services.search_intelligence import compute_search_intelligence
from leados.storage.base import StorageProvider
from leados.storage.mock import MockStorageProvider
from leados.storage.records import Company, Opportunity, OpportunityEvidence, ProviderRun, SourceDocument

logger = logging.getLogger(__name__)


class LiveDiscoveryEstimate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    queries_to_run: int
    max_exa_results: int
    estimated_candidates: int
    max_firecrawl_companies: int
    max_firecrawl_pages: int
    worst_case_exa_calls: int
    worst_case_firecrawl_calls: int
    dry_run: bool
    company_limit: int = 50
    configured_query_limit: int = 10


class LiveDiscoverySummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: str
    status: Literal["RUNNING", "COMPLETED", "PARTIAL", "FAILED"]
    data_mode: str = "LIVE"
    new_companies: int = 0
    known_companies: int = 0
    new_source_documents: int = 0
    prospects_created: int = 0
    relevant_prospects: int = 0
    exa_queries: int = 0
    exa_results: int = 0
    exa_unique_companies: int = 0
    source_supported_companies: int = 0
    exa_cache_hits: int = 0
    candidates_screened: int = 0
    candidates_passed_prescreen: int = 0
    candidates_discarded_low_relevance: int = 0
    firecrawl_requests: int = 0
    firecrawl_pages: int = 0
    firecrawl_cache_hits: int = 0
    firecrawl_skipped_low_relevance: int = 0
    firecrawl_skipped_recent_cache: int = 0
    firecrawl_errors: int = 0
    opportunities_created: int = 0
    duplicates_avoided: int = 0
    needs_research: int = 0
    errors: int = 0
    rejections: int = 0
    duration_ms: int = 0
    error: str | None = None
    dry_run: bool = False
    pipeline_run_id: str | None = None
    stage: str = "search"
    queries_completed: int = 0
    queries_total: int = 0
    candidates_processed: int = 0
    candidates_skipped_limit: int = 0
    next_query_offset: int = 0
    query_ids: list[str] = []
    dedup: dict[str, int] = {}
    firecrawl_attempts: int = 0
    firecrawl_skipped: int = 0
    firecrawl_verified_pages: int = 0
    opportunities_updated: int = 0
    qualification_counts: dict[str, int] = {}
    stopped: bool = False
    results: list[dict[str, Any]] = []


class LiveDiscoveryService:
    """Orchestrates credit-safe live market discovery using Exa and targeted deep research using Firecrawl."""

    def __init__(self, db: StorageProvider | None = None):
        self.db = db or MockStorageProvider()
        self.query_catalog = self._load_query_catalog()

    def _load_query_catalog(self) -> list[dict[str, Any]]:
        catalog_path = ROOT / "knowledge/search_queries/catalog.yaml"
        if catalog_path.exists():
            try:
                data = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
                return data.get("groups", []) if isinstance(data, dict) else []
            except Exception as exc:
                logger.warning("Error reading query catalog: %s", exc)
        return []

    def estimate(
        self,
        verticals: list[str] | None = None,
        max_queries: int | None = None,
        dry_run: bool | None = None,
        max_companies: int | None = None,
        query_offset: int = 0,
    ) -> LiveDiscoveryEstimate:
        active_queries = self._select_queries(verticals, max_queries, query_offset)
        q_count = len(active_queries)
        max_results = q_count * min(settings.max_exa_results_per_query, 10)
        is_dry_run = dry_run if dry_run is not None else settings.live_provider_dry_run

        company_limit = min(
            max_companies or settings.max_exa_candidates_per_run, settings.max_exa_candidates_per_run
        )
        max_companies = min(settings.max_firecrawl_companies_per_run, company_limit)
        max_pages = min(
            settings.max_firecrawl_pages_per_run,
            25,
            max_companies * min(settings.max_firecrawl_pages_per_company, 4),
        )

        return LiveDiscoveryEstimate(
            queries_to_run=q_count,
            max_exa_results=max_results,
            estimated_candidates=min(max_results, settings.max_exa_candidates_per_run),
            max_firecrawl_companies=max_companies,
            max_firecrawl_pages=max_pages,
            worst_case_exa_calls=q_count,
            worst_case_firecrawl_calls=0 if is_dry_run else max_pages,
            dry_run=is_dry_run,
            company_limit=company_limit,
            configured_query_limit=min(settings.max_exa_searches_per_run, len(self.query_catalog)),
        )

    def _select_queries(
        self,
        verticals: list[str] | None = None,
        max_queries: int | None = None,
        query_offset: int = 0,
    ) -> list[dict[str, Any]]:
        limit = max(
            1, min(max_queries or settings.max_exa_searches_per_run, settings.max_exa_searches_per_run)
        )
        selected = []
        cursor = query_offset % max(1, len(self.query_catalog))
        for group in [*self.query_catalog[cursor:], *self.query_catalog[:cursor]]:
            if not verticals:
                selected.append(group)
            else:
                group_verts = set(group.get("vertical_ids", []))
                if group_verts.intersection(verticals):
                    selected.append(group)
            if len(selected) >= limit:
                break
        return selected

    async def run(
        self,
        verticals: list[str] | None = None,
        max_queries: int | None = None,
        dry_run: bool | None = None,
        company_filter: str | None = None,
        progress: Callable[[LiveDiscoverySummary], None] | None = None,
        max_companies: int | None = None,
        query_offset: int = 0,
        should_stop: Callable[[], bool] | None = None,
        cache_only: bool = False,
    ) -> LiveDiscoverySummary:
        start_time = datetime.now(UTC)
        is_dry_run = dry_run if dry_run is not None else settings.live_provider_dry_run
        queries = self._select_queries(verticals, max_queries, query_offset)
        company_limit = min(
            max_companies or settings.max_exa_candidates_per_run, settings.max_exa_candidates_per_run
        )
        budget = ProviderBudget(
            max_exa_queries=min(
                max_queries or settings.max_exa_searches_per_run, settings.max_exa_searches_per_run
            ),
            max_exa_results=settings.max_exa_candidates_per_run,
            max_firecrawl_companies=min(settings.max_firecrawl_companies_per_run, company_limit),
            max_firecrawl_pages=min(settings.max_firecrawl_pages_per_run, 25),
            max_pages_per_company=min(settings.max_firecrawl_pages_per_company, 4),
        )
        exa = ExaSearchProvider(enabled=True, num_results=min(settings.max_exa_results_per_query, 10))
        crawler = FirecrawlCrawlerProvider(enabled=True, dry_run=False)
        exa.should_stop = should_stop
        crawler.should_stop = should_stop
        crawler.cache_only = cache_only
        run_record = ProviderRun(
            provider="exa+firecrawl",
            model=settings.live_research_mode,
            status="RUNNING",
            stage="discovery",
            state={
                "verticals": verticals,
                "dry_run": is_dry_run,
                "record_origin": "LIVE",
                "query_offset": query_offset,
            },
            metrics={
                "opportunities_created": 0,
                "duplicates_avoided": 0,
                "errors": 0,
                "rejections": 0,
            },
        )
        before_companies = {c.id for c in self.db.list(Company)}
        before_documents = {d.id for d in self.db.list(SourceDocument)}
        before_prospects = {p["id"] for p in live_prospects(self.db)}
        self.db.add(run_record)
        self.db.flush()
        summary = LiveDiscoverySummary(run_id=run_record.id, status="RUNNING", dry_run=is_dry_run)
        summary.query_ids = [group["id"] for group in queries]
        summary.next_query_offset = (query_offset + len(queries)) % max(1, len(self.query_catalog))
        summary.dedup = {
            "search_result": 0,
            "url": 0,
            "content": 0,
            "existing_company": 0,
            "company_signal": 0,
            "opportunity": 0,
            "updated_history": 0,
        }
        candidates = []
        semaphore = asyncio.Semaphore(settings.live_provider_concurrency)

        def report(stage: str):
            summary.stage = stage
            summary.duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
            if progress:
                progress(summary)

        try:
            selected = [None] if company_filter else queries
            summary.queries_total = len(selected)
            report("search")

            async def search(group):
                query = group.get("query", "") if group else None
                if group and not query:
                    return []
                cached = provider_cache.get_search(query) if query else None
                async with semaphore:
                    if should_stop and should_stop():
                        summary.stopped = True
                        return []
                    if not budget.can_query_exa():
                        return []
                    budget.record_exa_query()
                    try:
                        if cached is not None:
                            docs = cached
                            summary.exa_cache_hits += 1
                        elif cache_only:
                            summary.errors += 1
                            summary.error = "search_cache_miss"
                            return []
                        else:
                            summary.exa_queries += 1
                            docs = await exa.search(company=company_filter, query=query)
                        budget.current_exa_results += len(docs)
                        summary.exa_results += len(docs)
                        return docs
                    except Exception as error:
                        summary.errors += 1
                        summary.error = error.code if isinstance(error, ProviderError) else "exa_unavailable"
                        logger.warning("Live search: %s", summary.error)
                        return []
                    finally:
                        summary.queries_completed += 1
                        report("search")

            batches = await asyncio.gather(*(search(group) for group in selected))
            candidates = [candidate for batch in batches for candidate in batch]
            unique = []
            seen = set()
            for candidate in candidates:
                name = candidate.get("company", {}).get("name", "").strip().casefold()
                key = (name, canonical_url(str(candidate.get("source_url", ""))))
                if name and key not in seen:
                    seen.add(key)
                    unique.append(candidate)
                else:
                    summary.dedup["search_result"] += 1
            unique.sort(
                key=lambda doc: (
                    not qualify(doc).get("service_demand"),
                    doc.get("source_type") != "procurement_notice",
                )
            )
            summary.exa_unique_companies = len({c["company"]["name"] for c in unique})
            summary.candidates_screened = len(unique)
            company_locks: dict[str, asyncio.Lock] = {}
            selected_candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
            company_names: set[str] = set()
            seen_results_by_company: dict[str, dict[str, Any]] = {}
            for candidate in unique:
                candidate["record_origin"] = "LIVE"
                cname = candidate["company"]["name"].strip()
                ckey = company_dedup_key(cname)
                if ckey and ckey in seen_results_by_company:
                    existing_result = seen_results_by_company[ckey]
                    if "other_sources" not in existing_result:
                        existing_result["other_sources"] = []
                    other_src = {
                        "title": candidate.get("title") or candidate.get("source_name", "Source"),
                        "source_url": str(candidate.get("source_url", "")),
                        "published_date": candidate.get("published_date"),
                    }
                    if (
                        other_src["source_url"]
                        and other_src["source_url"] != existing_result.get("source_url")
                        and other_src not in existing_result["other_sources"]
                    ):
                        existing_result["other_sources"].append(other_src)
                    summary.dedup["search_result"] += 1
                    continue

                screen = pre_screen_candidate(candidate)
                assessment = qualify(candidate)
                result: dict[str, Any] = {
                    "id": digest(canonical_url(str(candidate.get("source_url", ""))))[:24],
                    "company": candidate["company"]["name"],
                    "source_url": str(candidate.get("source_url", "")),
                    "title": candidate.get("title") or candidate.get("source_name", "Source"),
                    "published_date": candidate.get("published_date"),
                    "snippet": (
                        candidate.get("snippet")
                        if isinstance(candidate.get("snippet"), str)
                        else ""
                    )[:1200],
                    "relevance": screen.relevance_score,
                    "status": "PREVIEW" if is_dry_run else "QUEUED",
                    "reason": screen.rationale,
                    "opportunity_ids": [],
                    "other_sources": [],
                    "record_origin": "LIVE",
                    "source_origin": "LIVE",
                    "qualification": assessment,
                    "provider_score": candidate.get("provider_score"),
                    "firecrawl_decision": "NEEDS_ADDITIONAL_RESEARCH"
                    if screen.qualifies
                    else "LOW_RELEVANCE",
                    "firecrawl_decisions": [],
                    "search_intelligence": compute_search_intelligence(
                        self.db, candidate, assessment, []
                    ),
                }
                if ckey:
                    seen_results_by_company[ckey] = result
                summary.results.append(result)
                name = candidate["company"]["name"].casefold()
                if len(company_names) >= company_limit and name not in company_names:
                    result.update(
                        status="SKIPPED_COMPANY_LIMIT",
                        firecrawl_decision="BUDGET_EXHAUSTED",
                        reason="The configured company ceiling was reached; retained for a later run.",
                    )
                    summary.candidates_skipped_limit += 1
                    continue
                if len(selected_candidates) >= settings.max_exa_candidates_per_run:
                    result.update(
                        status="SKIPPED_CANDIDATE_LIMIT",
                        firecrawl_decision="BUDGET_EXHAUSTED",
                        reason="The candidate research ceiling was reached; retained for a later run.",
                    )
                    summary.candidates_skipped_limit += 1
                    continue
                company_names.add(name)
                if document_heading(candidate["company"]["name"]):
                    result.update(
                        status="SKIPPED_IDENTITY",
                        research_status="NEEDS_RESEARCH",
                        reason="Company identity is unconfirmed: this name is a source heading. No company record or crawl created.",
                        firecrawl_decision="NO_TARGET_URL",
                    )
                    continue
                if not screen.qualifies:
                    summary.candidates_discarded_low_relevance += 1
                    result["status"] = "TOPIC_MATCH_ONLY"
                    result["reason"] = assessment["reason"]
                    continue
                summary.candidates_passed_prescreen += 1
                if is_dry_run:
                    continue  # Preview only; no business records, crawl, embeddings or LLM calls.
                selected_candidates.append((candidate, result))
            report("screen" if is_dry_run else "crawl")

            async def enrich(candidate: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
                enriched: dict[str, Any] = dict(candidate)
                existing = self.db.first(
                    SourceDocument, url_hash=digest(canonical_url(str(candidate["source_url"])))
                )
                if (
                    existing
                    and existing.record_origin == "LIVE"
                    and existing.retrieved_at
                    >= datetime.now(UTC) - timedelta(hours=settings.firecrawl_cache_ttl_hours)
                ):
                    stored = {
                        **candidate,
                        "snippet": existing.snippet,
                        "confidence": existing.confidence,
                        "company_match": existing.company_match,
                        "conflict": existing.conflict,
                        "published_date": existing.published_date.isoformat()
                        if existing.published_date
                        else None,
                        "provenance": existing.provenance,
                    }
                    recent_failure = existing.provenance.get("source_error") and (
                        cache_only or existing.retrieved_at >= datetime.now(UTC) - timedelta(minutes=15)
                    )
                    if recent_failure:
                        enriched = {
                            **stored,
                            "crawler_error": existing.provenance["source_error"],
                            "crawl_cache_reused": True,
                        }
                        result["firecrawl_decision"] = (
                            "ROBOTS_OR_ACCESS_RESTRICTED"
                            if "restricted" in str(existing.provenance["source_error"]).casefold()
                            else "PROVIDER_ERROR"
                        )
                        result["firecrawl_decisions"] = [
                            {
                                "decision": result["firecrawl_decision"],
                                "url": candidate["source_url"],
                                "cache_reused": True,
                                "reason": "Recent saved failure reused; no immediate paid retry",
                            }
                        ]
                    elif source_sufficient(stored):
                        enriched = stored
                        result["firecrawl_decision"] = "SOURCE_ALREADY_SUFFICIENT"
                if should_stop and should_stop():
                    summary.stopped = True
                    result["firecrawl_decision"] = "BUDGET_EXHAUSTED"
                    result["reason"] = "Run stopped; no further provider requests executed."
                elif result["firecrawl_decision"] not in {
                    "SOURCE_ALREADY_SUFFICIENT",
                    "ROBOTS_OR_ACCESS_RESTRICTED",
                    "PROVIDER_ERROR",
                }:
                    if source_sufficient(candidate):
                        result["firecrawl_decision"] = "SOURCE_ALREADY_SUFFICIENT"
                    elif settings.live_research_mode != "EXA_ONLY":
                        company_key = candidate["company"].get("domain") or candidate["company"]["name"]
                        lock = company_locks.setdefault(company_key, asyncio.Lock())
                        async with semaphore, lock:
                            if should_stop and should_stop():
                                summary.stopped = True
                                result["firecrawl_decision"] = "BUDGET_EXHAUSTED"
                            else:
                                try:
                                    enriched = await crawler.enrich_candidate(candidate, budget=budget)
                                    result["firecrawl_decision"] = enriched.get(
                                        "firecrawl_decision", "NEEDS_ADDITIONAL_RESEARCH"
                                    )
                                    result["firecrawl_decisions"] = enriched.get("firecrawl_decisions", [])
                                except Exception as error:
                                    result["firecrawl_decision"] = "PROVIDER_ERROR"
                                    enriched["crawler_error"] = (
                                        error.code if isinstance(error, ProviderError) else "scrape_failed"
                                    )
                                    enriched["crawler_status"] = "NEEDS_RESEARCH"
                    else:
                        result["firecrawl_decision"] = "NEEDS_ADDITIONAL_RESEARCH"
                state = enriched.get("crawler_status", "")
                if state == "CACHED" or enriched.get("crawl_cache_reused"):
                    summary.firecrawl_cache_hits += 1
                if result["firecrawl_decision"] in {"PROVIDER_ERROR", "ROBOTS_OR_ACCESS_RESTRICTED"}:
                    summary.firecrawl_errors += 1
                    result["provider_error"] = enriched.get("crawler_error", "scrape_failed")
                elif result["firecrawl_decision"] != "CALL_EXECUTED":
                    summary.firecrawl_skipped += 1
                raw_snippet = enriched.get("snippet")
                result["snippet"] = (raw_snippet if isinstance(raw_snippet, str) else "")[:1200]
                result["qualification"] = qualify(enriched)
                result["status"] = result["qualification"]["status"]
                result["reason"] = result["qualification"]["reason"]
                summary.candidates_processed += 1
                report("crawl")
                return enriched

            documents = await asyncio.gather(*(enrich(c, r) for c, r in selected_candidates))
            documents = [
                doc for primary in documents for doc in [primary, *primary.get("additional_documents", [])]
            ]

            def candidate_company_data(cid):
                from leados.storage.records import Company

                company = self.db.get(Company, cid)
                return (
                    {"name": company.canonical_name, "sector": company.sector, "country": company.country}
                    if company
                    else {}
                )

            if documents:
                providers = get_providers(live=settings.live_research_mode == "FULL_LIVE")
                for provider in (providers.llm, providers.embeddings):
                    if hasattr(provider, "client"):
                        cast(Any, provider).should_stop = should_stop
                pipeline = Pipeline(self.db, providers=providers)
                pipeline_run = await pipeline.run_documents(
                    documents, company_filter, live=True, promote_candidates=True, progress=lambda stage: report(stage)
                )
                summary.pipeline_run_id = pipeline_run.id
                summary.opportunities_created = pipeline_run.metrics.get("opportunities_created", 0)
                summary.duplicates_avoided += pipeline_run.metrics.get("duplicates_avoided", 0)
                for category, count in pipeline_run.metrics.get("dedup", {}).items():
                    summary.dedup[category] = summary.dedup.get(category, 0) + count
                summary.opportunities_updated = len(
                    set(pipeline_run.state.get("updated_opportunity_ids", []))
                )
                summary.errors += pipeline_run.metrics.get("errors", 0)
                summary.rejections += pipeline_run.metrics.get("rejections", 0)
                for result in summary.results:
                    if result["status"] in {
                        "SKIPPED_COMPANY_LIMIT",
                        "SKIPPED_CANDIDATE_LIMIT",
                        "TOPIC_MATCH_ONLY",
                    }:
                        continue
                    source = self.db.first(
                        SourceDocument, url_hash=digest(canonical_url(result["source_url"]))
                    )
                    if not source:
                        continue
                    all_ids = [
                        link.opportunity_id
                        for link in self.db.list(OpportunityEvidence, document_id=source.id)
                    ]
                    result["historical_opportunity_ids"] = all_ids
                    ids = [
                        oid
                        for oid in all_ids
                        if (op := self.db.get(Opportunity, oid)) and qualified_opportunity(op)
                    ]
                    result["opportunity_ids"] = ids
                    result["qualification"] = qualify(
                        {
                            **source.model_dump(mode="json"),
                            "company": candidate_company_data(source.company_id),
                        }
                    )
                    result["search_intelligence"] = compute_search_intelligence(
                        self.db,
                        candidate=result,
                        qualification=result["qualification"],
                        opportunity_ids=ids,
                    )
                    result["status"] = result["qualification"]["status"]
                    result["reason"] = result["qualification"]["reason"]
                    if ids:
                        result["status"] = (
                            "EXISTING_OPPORTUNITY"
                            if not summary.opportunities_created
                            else "VERIFIED_OPPORTUNITY"
                        )
                    elif result["status"] == "QUALIFIED_SIGNAL":
                        result["status"] = "NEEDS_RESEARCH"
                        result["reason"] = (
                            "Commercial requirement found; evidence audit or AI research still requires attention."
                        )
                summary.needs_research = sum(
                    result["status"] == "NEEDS_RESEARCH" for result in summary.results
                )
                if pipeline_run.status == "FAILED":
                    summary.error = pipeline_run.error or "pipeline_failed"
                    summary.status = "FAILED"
                else:
                    summary.status = pipeline_run.status
                    summary.error = pipeline_run.error or summary.error
            else:
                summary.status = "COMPLETED"
            if summary.error and summary.status != "FAILED":
                summary.status = "PARTIAL" if candidates else "FAILED"
            if summary.firecrawl_errors:
                if summary.status == "COMPLETED":
                    summary.status = "PARTIAL"
                summary.errors += summary.firecrawl_errors
        except Exception as error:
            summary.status = "FAILED"
            summary.error = error.code if isinstance(error, ProviderError) else "live_discovery_failed"
            logger.exception("Live discovery failed: %s (%s)", summary.error, type(error).__name__)
        finally:
            summary.source_supported_companies = len(
                {
                    c["company"]["name"].casefold()
                    for c in candidates
                    if not document_heading(c.get("company", {}).get("name", ""))
                    and c.get("company_match")
                    and company_name_supported(c.get("company", {}), str(c.get("snippet", "")))
                }
            )
            after_prospects = live_prospects(self.db)
            summary.new_companies = len({c.id for c in self.db.list(Company)} - before_companies)
            summary.new_source_documents = len(
                {d.id for d in self.db.list(SourceDocument)} - before_documents
            )
            summary.prospects_created = len({p["id"] for p in after_prospects} - before_prospects)
            matched_urls = {r["source_url"] for r in summary.results}
            summary.relevant_prospects = sum(
                any(s["url"] in matched_urls for s in p["sources"]) for p in after_prospects
            )
            summary.known_companies = summary.dedup.get("existing_company", 0)
            for result in summary.results:
                prospect = next(
                    (
                        p
                        for p in after_prospects
                        if any(s["url"] == result["source_url"] for s in p["sources"])
                    ),
                    None,
                )
                if prospect:
                    result["prospect"] = {
                        k: prospect[k]
                        for k in ("trigger", "vertical", "recommended_service", "research_status", "id")
                    }
                status = result.get("status", "")
                result["research_status"] = (
                    "NEEDS_RESEARCH"
                    if status == "SKIPPED_IDENTITY"
                    else "VERIFIED_QUALIFIED"
                    if status == "VERIFIED_OPPORTUNITY"
                    else "DUPLICATE_EXISTING"
                    if status == "EXISTING_OPPORTUNITY"
                    else prospect["research_status"]
                    if prospect
                    else "NOT_A_BUYER"
                    if result.get("qualification", {}).get("status") == "NOT_A_BUYER"
                    else "NEEDS_RESEARCH"
                    if result.get("qualification", {}).get("status") == "NEEDS_RESEARCH"
                    else "NOT_RELEVANT"
                )
            summary.exa_queries = exa.actual_requests
            summary.firecrawl_requests = crawler.actual_requests
            summary.firecrawl_attempts = budget.current_firecrawl_pages
            decisions = [d for result in summary.results for d in result.get("firecrawl_decisions", [])]
            summary.firecrawl_pages = sum(
                d["decision"] == "CALL_EXECUTED" and d.get("status") == "SUCCESS" for d in decisions
            )
            summary.firecrawl_verified_pages = sum(
                r["status"] in {"VERIFIED_OPPORTUNITY", "EXISTING_OPPORTUNITY"}
                and r.get("firecrawl_decision") in {"CALL_EXECUTED", "CACHE_REUSED"}
                for r in summary.results
            )
            summary.duplicates_avoided = sum(
                value for key, value in summary.dedup.items() if key != "updated_history"
            )
            summary.qualification_counts = {
                status: sum(r["status"] == status for r in summary.results)
                for status in {r["status"] for r in summary.results}
            }
            if summary.stopped:
                summary.status, summary.error = "PARTIAL", "discovery_stopped"
            summary.stage = "complete" if summary.status != "FAILED" else "failed"
            summary.duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
            run_record = self.db.get(ProviderRun, run_record.id) or run_record
            run_record.status = summary.status
            run_record.stage = "store"
            run_record.duration_ms = summary.duration_ms
            run_record.error = summary.error
            run_record.completed_at = datetime.now(UTC)
            run_record.metrics = summary.model_dump(mode="json", exclude={"results"})
            run_record.state = {**run_record.state, "discovery_results": summary.results}
            self.db.add(run_record)
            self.db.flush()
        # application_storage syncs the master view once after the transaction commits.
        return summary
