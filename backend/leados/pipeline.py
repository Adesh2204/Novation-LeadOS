import asyncio
import json
import logging
from collections.abc import Callable
from datetime import date
from functools import partial
from time import perf_counter
from typing import Literal, cast
from urllib.parse import urlsplit

from pydantic import HttpUrl, ValidationError

from leados.config import settings
from leados.engine import (
    audit_evidence,
    canonical_url,
    detect_signals,
    digest,
    resolve_company,
    route_verticals,
    score_opportunity,
)
from leados.knowledge import Knowledge, knowledge
from leados.providers.base import ProviderError, ProviderExecutor, ProviderPolicy
from leados.providers.factory import Providers, get_providers
from leados.providers.mock.crawler import MockCrawlerProvider
from leados.providers.mock.embeddings import MockEmbeddingProvider
from leados.providers.mock.llm import MockLLMProvider
from leados.qualification import SCORE_VERSION, access_restricted, qualify
from leados.schemas import AssertionType, AuditStatus, Claim, Evidence, MarketDocument, ResearchOutput
from leados.storage.base import StorageError, StorageProvider
from leados.storage.records import (
    AuditLog,
    Company,
    CompanySignal,
    DecisionMakerRole,
    HumanReviewTask,
    Opportunity,
    OpportunityEvidence,
    OutreachDraft,
    ProviderRun,
    ScoreComponent,
    Service,
    Signal,
    Source,
    SourceDocument,
    Stage,
    now,
)

log = logging.getLogger("leados.pipeline")
STAGES = ["discovery", "normalise", "resolve", "detect", "route", "research", "score", "audit", "store"]


def evidence_for(db: StorageProvider, ids: list[str]) -> list[Evidence]:
    result = []
    for did in ids:
        document = db.get(SourceDocument, did)
        if document is None:
            continue
        source = db.get(Source, document.source_id)
        assert source is not None
        result.append(
            Evidence(
                id=document.id,
                source_url=HttpUrl(document.source_url),
                source_name=source.name,
                source_type=source.source_type,
                published_date=document.published_date,
                retrieved_at=document.retrieved_at,
                snippet=document.snippet,
                confidence=document.confidence,
                content_hash=document.content_hash,
                assertion_type=AssertionType(document.assertion_type),
                company_match=document.company_match,
                conflict=document.conflict,
                author=document.author,
                jurisdiction=document.jurisdiction,
                language=document.language,
            )
        )
    return result


class Pipeline:
    def __init__(
        self,
        db: StorageProvider,
        providers: Providers | None = None,
        kb: Knowledge = knowledge,
        as_of: date | None = None,
    ):
        self.db = db
        self.providers = providers or get_providers()
        self.kb = kb
        self.as_of = as_of or date.today()
        self.research_failure: str | None = None
        self.executor = ProviderExecutor(
            ProviderPolicy(
                timeout_seconds=settings.provider_timeout_seconds,
                max_attempts=settings.provider_max_attempts,
                requests_per_minute=settings.provider_requests_per_minute,
            )
        )

    def start(self, company: str | None = None) -> ProviderRun:
        self.kb.seed(self.db)
        run = ProviderRun(
            provider="provider_bundle",
            model=self.providers.llm.model,
            status="RUNNING",
            stage="start",
            state={"company_filter": company, "as_of": str(self.as_of)},
            metrics={
                "companies_discovered": 0,
                "signals_found": 0,
                "opportunities_created": 0,
                "duplicates_avoided": 0,
                "rejections": 0,
                "errors": 0,
                "processed": 0,
                "successful": 0,
                "failed": 0,
                "dedup": {
                    "existing_company": 0,
                    "url": 0,
                    "content": 0,
                    "company_signal": 0,
                    "opportunity": 0,
                    "updated_history": 0,
                },
            },
        )
        self.db.add(run)
        self.db.flush()
        return run

    async def run(self, company: str | None = None) -> ProviderRun:
        run = self.start(company)
        for stage in STAGES:
            run = await self.advance(run, stage)
            if run.status == "FAILED":
                break
        return run

    async def run_documents(
        self,
        documents: list[dict],
        company: str | None = None,
        *,
        live: bool = False,
        promote_candidates: bool = False,
        progress: Callable[[str], None] | None = None,
    ) -> ProviderRun:
        """Enter pre-discovered documents into the same audited, resumable pipeline."""
        run = self.start(company)
        run.state = {
            **run.state,
            "raw": documents,
            "live_documents": live,
            "promote_candidates": promote_candidates or bool(company),
        }
        run.stage = "discovery"
        self.providers.crawler = MockCrawlerProvider()  # These URLs have already been scraped.
        self.db.add(
            AuditLog(module="discovery", input_ref=run.id, output_ref=run.id, provider="exa", success=True)
        )
        for stage in STAGES[1:]:
            if progress:
                progress(stage)
            run = await self.advance(run, stage)
            if run.status == "FAILED":
                break
        return run

    async def advance(self, run: ProviderRun, stage: str) -> ProviderRun:
        with self.db.transaction():
            current = self.db.get(ProviderRun, run.id)
            if current is None:
                raise ValueError("run_not_found")
            result = await self._advance(current, stage)
        # A savepoint rollback restores a typed copy. Resolve by UUID and keep callers'
        # existing run handle current, including the revision assigned on commit.
        if result is not run:
            for field in ProviderRun.model_fields:
                setattr(run, field, getattr(result, field))
        return run

    async def _advance(self, run: ProviderRun, stage: str) -> ProviderRun:
        if stage == run.stage:
            return run  # n8n retry of a completed stage is idempotent.
        expected = (
            STAGES[0]
            if run.stage == "start"
            else (STAGES[STAGES.index(run.stage) + 1] if run.stage in STAGES[:-1] else None)
        )
        if run.status != "RUNNING" or expected != stage:
            raise ValueError(f"stage_order: expected {expected}")
        started = perf_counter()
        state = json.loads(json.dumps(run.state))
        metrics = dict(run.metrics)
        try:
            with self.db.begin_nested():
                state, metrics = await self._stage(stage, state, metrics)
                run = self.db.get(ProviderRun, run.id) or run
                run.state, run.metrics, run.stage = state, metrics, cast(Stage, stage)
                if stage == "store":
                    run.status = "PARTIAL" if metrics.get("errors", 0) else "COMPLETED"
                    run.error = next(
                        (c["provider_error"] for c in state.get("candidates", []) if c.get("provider_error")),
                        None,
                    )
                self.db.flush()
        except Exception as exc:
            # Do not serialize raw exception text: provider/DB exceptions may contain secrets.
            run = self.db.get(ProviderRun, run.id) or run
            run.status = "FAILED"
            run.error = exc.code if isinstance(exc, ProviderError) else type(exc).__name__
            run.metrics = {**run.metrics, "errors": run.metrics.get("errors", 0) + 1}
        elapsed = int((perf_counter() - started) * 1000)
        run.duration_ms = (run.duration_ms or 0) + elapsed
        if run.status in {"COMPLETED", "PARTIAL", "FAILED"}:
            run.completed_at = now()
        self.db.add(
            AuditLog(
                module=stage,
                input_ref=run.id,
                output_ref=run.id,
                provider=self._provider_for(stage),
                model=self.providers.llm.model if stage == "research" else None,
                duration_ms=elapsed,
                success=run.status != "FAILED",
                error=run.error,
            )
        )
        self.db.flush()
        log.info(
            json.dumps(
                {
                    "run_id": run.id,
                    "stage": stage,
                    "status": run.status,
                    "duration_ms": elapsed,
                    "metrics": run.metrics,
                    "error": run.error,
                }
            )
        )
        return run

    def _provider_for(self, stage: str) -> str | None:
        return {
            "discovery": self.providers.search.name,
            "normalise": self.providers.crawler.name,
            "research": self.providers.llm.name,
            "store": self.providers.contacts.name,
        }.get(stage)

    async def _stage(self, stage: str, state: dict, metrics: dict) -> tuple[dict, dict]:
        if stage == "discovery":
            state["raw"] = await self.executor.call(
                lambda: self.providers.search.search(state["company_filter"])
            )
        elif stage == "normalise":
            state["documents"] = []
            for raw in state.pop("raw"):
                try:
                    crawled = await self.executor.call(partial(self.providers.crawler.crawl, raw))
                    document = MarketDocument.model_validate(
                        {k: v for k, v in crawled.items() if k in MarketDocument.model_fields}
                    )
                    document.source_url = HttpUrl(canonical_url(str(document.source_url)))
                    state["documents"].append(document.model_dump(mode="json"))
                except (ValidationError, ValueError):
                    metrics["errors"] += 1
                    self.db.add(
                        AuditLog(
                            module="normalise_document",
                            input_ref=None,
                            output_ref=None,
                            provider=self.providers.crawler.name,
                            success=False,
                            error="invalid_document",
                        )
                    )
        elif stage == "resolve":
            state["resolved"] = []
            origin_mode: Literal["LIVE", "MOCK"] = "LIVE" if state.get("live_documents") else "MOCK"
            for row in state.pop("documents"):
                document = MarketDocument.model_validate(row)
                try:
                    with self.db.begin_nested():
                        company, created = resolve_company(self.db, document.company)
                        if company.record_origin == "LEGACY_UNKNOWN":
                            company.record_origin = origin_mode
                            company.provenance = {
                                "provider": "exa" if origin_mode == "LIVE" else "mock_search"
                            }
                        elif company.record_origin != origin_mode:
                            raise StorageError("origin_identity_conflict", "Company")
                        metrics["companies_discovered"] += int(created)
                        metrics["duplicates_avoided"] += int(not created)
                        metrics["dedup"]["existing_company"] += int(not created)
                        url = canonical_url(str(document.source_url))
                        content_hash = digest(document.snippet.strip())
                        existing = self.db.first(SourceDocument, url_hash=digest(url)) or self.db.first(
                            SourceDocument, content_hash=content_hash
                        )
                        if existing:
                            metrics["duplicates_avoided"] += 1
                            if existing.company_id != company.id:
                                metrics["rejections"] += 1
                                continue
                            doc = existing
                            metrics["dedup"]["url" if existing.url_hash == digest(url) else "content"] += 1
                            # Fresh page content replaces highlights; highlights cannot degrade a full page.
                            fresh_page = document.provenance.get("firecrawl", {}).get("status") == "SUCCESS"
                            replace_blocked_page = (
                                origin_mode == "LIVE"
                                and document.provenance.get("provider") == "exa"
                                and access_restricted(doc.snippet)
                                and not access_restricted(document.snippet)
                            )
                            if (fresh_page or replace_blocked_page) and content_hash != doc.content_hash:
                                doc.content_history = [
                                    *doc.content_history,
                                    {
                                        "content_hash": doc.content_hash,
                                        "snippet": doc.snippet,
                                        "published_date": str(doc.published_date)
                                        if doc.published_date
                                        else None,
                                        "retrieved_at": doc.retrieved_at.isoformat(),
                                        "provenance": doc.provenance,
                                    },
                                ]
                                doc.snippet, doc.content_hash = document.snippet, content_hash
                                doc.confidence, doc.company_match = (
                                    document.confidence,
                                    document.company_match,
                                )
                                doc.published_date = document.published_date or doc.published_date
                                doc.provenance = document.provenance
                                doc.retrieved_at = now()
                                metrics["dedup"]["updated_history"] += 1
                            doc.last_seen_at = now()
                        else:
                            origin = urlsplit(url).netloc
                            source = self.db.first(Source, origin=origin)
                            if source is None:
                                source = Source(
                                    name=document.source_name,
                                    source_type=document.source_type,
                                    origin=origin,
                                    reliability=document.confidence,
                                    record_origin=origin_mode,
                                    provenance={
                                        "provider": "exa" if origin_mode == "LIVE" else "mock_search"
                                    },
                                )
                                self.db.add(source)
                                self.db.flush()
                            doc = SourceDocument(
                                source_id=source.id,
                                company_id=company.id,
                                source_url=url,
                                url_hash=digest(url),
                                content_hash=content_hash,
                                record_origin=origin_mode,
                                provenance={
                                    **document.provenance,
                                    "provider": "exa" if origin_mode == "LIVE" else "mock_search",
                                },
                                **document.model_dump(
                                    exclude={
                                        "company",
                                        "source_url",
                                        "source_name",
                                        "source_type",
                                        "record_origin",
                                        "provenance",
                                        "provider_score",
                                    }
                                ),
                            )
                            self.db.add(doc)
                            self.db.flush()
                        if doc.id not in state["resolved"]:
                            state["resolved"].append(doc.id)
                except StorageError as exc:
                    if not exc.code.startswith("quarantined"):
                        raise
                    metrics["errors"] += 1
                    metrics["rejections"] += 1
                    self.db.add(
                        AuditLog(
                            module="resolve_document",
                            provider=self.providers.crawler.name,
                            success=False,
                            error=exc.code,
                        )
                    )
        elif stage == "detect":
            state["detected"] = []
            for did in state["resolved"]:
                detected_doc = self.db.get(SourceDocument, did)
                assert detected_doc is not None
                ids = detect_signals(
                    detected_doc.snippet, self.kb.signals, live=state.get("live_documents", False)
                )
                qualification = {}
                if state.get("live_documents"):
                    owner = self.db.get(Company, detected_doc.company_id)
                    assert owner is not None
                    qualification = qualify(
                        {
                            **detected_doc.model_dump(mode="json"),
                            "company": {
                                "name": owner.canonical_name,
                                "sector": owner.sector,
                                "country": owner.country,
                            },
                        }
                    )
                    ids = (
                        qualification["signal_ids"]
                        if qualification["status"] == "QUALIFIED_SIGNAL"
                        else list(dict.fromkeys([*ids, *qualification["signal_ids"]]))
                    )
                    state.setdefault("source_qualifications", {})[did] = qualification
                if not ids:
                    metrics["rejections"] += 1
                for sid in ids:
                    event_key = (
                        str(detected_doc.published_date)
                        if detected_doc.published_date
                        else "undated:" + detected_doc.content_hash
                    )
                    if state.get("live_documents"):
                        event_key = (
                            "event-v2:"
                            + sid
                            + ":"
                            + (
                                str(detected_doc.published_date)[:7]
                                if detected_doc.published_date
                                else "undated:" + detected_doc.content_hash
                            )
                        )
                    if qualification.get("event_reference"):
                        event_key += ":ref:" + qualification["event_reference"]
                    runtime_signal = self.db.first(Signal, code=sid)
                    assert runtime_signal is not None
                    signal = self.db.first(
                        CompanySignal,
                        company_id=detected_doc.company_id,
                        signal_id=runtime_signal.id,
                        event_key=event_key,
                    )
                    if (
                        signal is None
                        and state.get("live_documents")
                        and detected_doc.published_date
                        and not qualification.get("event_reference")
                    ):
                        # Match legacy event keys without modifying fingerprints or historical scores.
                        signal = next(
                            (
                                s
                                for s in self.db.list(
                                    CompanySignal,
                                    company_id=detected_doc.company_id,
                                    signal_id=runtime_signal.id,
                                )
                                if s.event_date
                                and str(s.event_date)[:7] == str(detected_doc.published_date)[:7]
                            ),
                            None,
                        )
                    if signal is None:
                        signal = CompanySignal(
                            company_id=detected_doc.company_id,
                            signal_id=runtime_signal.id,
                            signal_key=sid,
                            event_key=event_key,
                            event_date=detected_doc.published_date,
                            confidence=detected_doc.confidence,
                            evidence_ids=[did],
                            record_origin=detected_doc.record_origin,
                            provenance={"source_ids": [did]},
                            qualification=qualification,
                        )
                        self.db.add(signal)
                        self.db.flush()
                        metrics["signals_found"] += 1
                    else:
                        metrics["duplicates_avoided"] += 1
                        signal.last_seen_at = now()
                        metrics["dedup"]["company_signal"] += 1
                        if qualification:
                            signal.qualification = qualification
                        if did not in signal.evidence_ids:
                            signal.evidence_ids = [*signal.evidence_ids, did]
                    if signal.id not in state["detected"]:
                        state["detected"].append(signal.id)
        elif stage == "route":
            state["candidates"] = []
            for sid in state["detected"]:
                signal = self.db.get(CompanySignal, sid)
                assert signal is not None
                routes = route_verticals(self.kb.signals[signal.signal_key])
                if state.get("live_documents"):
                    # Reassess all linked sources, allowing better evidence to qualify weak events.
                    owner = self.db.get(Company, signal.company_id)
                    assert owner is not None
                    assessments = [
                        qualify(
                            {
                                **source_record.model_dump(mode="json"),
                                "company": {
                                    "name": owner.canonical_name,
                                    "sector": owner.sector,
                                    "country": owner.country,
                                },
                            }
                        )
                        for did in signal.evidence_ids
                        if (source_record := self.db.get(SourceDocument, did)) is not None
                    ]
                    supported = [q for q in assessments if q["status"] == "QUALIFIED_SIGNAL"]
                    demand_supported = [q for q in assessments if q.get("service_demand")]
                    qualification = supported[0] if supported else (demand_supported[0] if demand_supported else signal.qualification)
                    signal.qualification = qualification
                    routes = [
                        {"vertical_id": vid, "rank": i + 1, "match": 1}
                        for i, vid in enumerate(
                            vid
                            for vid in qualification.get("vertical_ids", [])
                            if vid in self.kb.signals[signal.signal_key].vertical_ids
                        )
                    ]
                    if not routes and qualification.get("vertical_ids"):
                        routes = [
                            {"vertical_id": vid, "rank": i + 1, "match": 1}
                            for i, vid in enumerate(qualification.get("vertical_ids", []))
                        ]
                    if not routes:
                        routes = route_verticals(self.kb.signals[signal.signal_key])
                    # Historical weak opportunities remain inspectable but leave qualified views.
                    for old in self.db.list(Opportunity, company_signal_id=sid):
                        old.qualification = qualification
                for route in routes:
                    existing_opportunity = self.db.first(
                        Opportunity, company_signal_id=sid, vertical_id=route["vertical_id"]
                    )
                    if existing_opportunity:
                        existing_opportunity.updated_at = now()
                        metrics["duplicates_avoided"] += 1
                        metrics["dedup"]["opportunity"] += 1
                        new_evidence = False
                        for did in signal.evidence_ids:
                            if not self.db.first(
                                OpportunityEvidence, opportunity_id=existing_opportunity.id, document_id=did
                            ):
                                self.db.add(
                                    OpportunityEvidence(
                                        opportunity_id=existing_opportunity.id, document_id=did
                                    )
                                )
                                metrics["dedup"]["updated_history"] += 1
                                new_evidence = True
                        if state.get("live_documents"):
                            existing_opportunity.qualification = signal.qualification
                            evidence = evidence_for(self.db, signal.evidence_ids)
                            hashes = {e.id: e.content_hash for e in evidence}
                            if (signal.qualification.get("status") == "QUALIFIED_SIGNAL" or signal.qualification.get("service_demand")) and (
                                new_evidence
                                or existing_opportunity.score_version != SCORE_VERSION
                                or hashes != existing_opportunity.score_inputs.get("evidence_hashes")
                            ):
                                self._reevaluate(existing_opportunity, signal, evidence)
                                state.setdefault("updated_opportunity_ids", []).append(
                                    existing_opportunity.id
                                )
                    elif (
                        not state.get("live_documents")
                        or signal.qualification.get("status") == "QUALIFIED_SIGNAL"
                        or (
                            state.get("promote_candidates")
                            and signal.qualification.get("service_demand")
                        )
                    ):
                        state["candidates"].append(
                            {
                                "company_signal_id": sid,
                                **route,
                                "qualification": signal.qualification if state.get("live_documents") else {},
                            }
                        )
        elif stage in {"research", "score", "audit", "store"}:
            if stage == "research":
                semaphore = asyncio.Semaphore(settings.live_provider_concurrency)

                async def research(candidate):
                    async with semaphore:
                        await self._research_candidate(candidate, metrics)

                outcomes = await asyncio.gather(
                    *(research(candidate) for candidate in state["candidates"]), return_exceptions=True
                )
                # Settle every task before rolling back the stage if a provider raises.
                for outcome in outcomes:
                    if isinstance(outcome, BaseException):
                        raise outcome
                return state, metrics
            for candidate in state["candidates"]:
                signal = self.db.get(CompanySignal, candidate["company_signal_id"])
                assert signal is not None
                candidate_company = self.db.get(Company, signal.company_id)
                assert candidate_company is not None
                definition = self.kb.signals[signal.signal_key]
                vertical = self.kb.verticals[candidate["vertical_id"]]
                evidence = evidence_for(self.db, signal.evidence_ids)
                if stage == "score":
                    candidate["scoring"] = score_opportunity(
                        definition,
                        vertical.id,
                        candidate_company,
                        evidence,
                        candidate["research"],
                        self.kb,
                        date.fromisoformat(state["as_of"]),
                    )
                elif stage == "audit":
                    status, reasons, confidence = audit_evidence(
                        evidence,
                        definition,
                        date.fromisoformat(state["as_of"]),
                        candidate["research"]["inferences"],
                        self.kb,
                        live=state.get("live_documents", False),
                    )
                    if candidate.get("provider_error"):
                        status = AuditStatus.NEEDS_RESEARCH
                        reasons = [*reasons, f"AI research requires attention: {candidate['provider_error']}"]
                    candidate["audit"] = {"status": status, "reasons": reasons, "confidence": confidence}
                    metrics["rejections"] += int(status == "REJECTED")
                else:
                    metrics["processed"] = metrics.get("processed", 0) + 1
                    try:
                        with self.db.begin_nested():
                            oid = await self._store(candidate, candidate_company, signal, evidence)
                        state.setdefault("opportunity_ids", []).append(oid)
                        metrics["opportunities_created"] += 1
                        metrics["successful"] = metrics.get("successful", 0) + 1
                    except StorageError as exc:
                        metrics["failed"] = metrics.get("failed", 0) + 1
                        metrics["errors"] += 1
                        state.setdefault("storage_errors", []).append(
                            {"company_id": candidate_company.id, "code": exc.code}
                        )
                        self.db.add(
                            AuditLog(
                                module="store_candidate",
                                input_ref=candidate_company.id,
                                success=False,
                                error=exc.code,
                            )
                        )
            if stage == "store":
                scores = [c["scoring"]["score"] for c in state["candidates"]]
                metrics["average_score"] = round(sum(scores) / len(scores), 2) if scores else 0
                state["human_review_ids"] = [
                    c["opportunity_id"]
                    for c in state["candidates"]
                    if c.get("opportunity_id")
                    and c["scoring"]["score"] >= 80
                    and c["audit"]["status"] == "VERIFIED"
                ]
        return state, metrics

    def _reevaluate(self, opportunity: Opportunity, signal: CompanySignal, evidence: list[Evidence]):
        """A new versioned evaluation preserves the previous score and all review records."""
        company = self.db.get(Company, opportunity.company_id)
        assert company is not None
        definition = self.kb.signals[signal.signal_key]
        parts = self.db.list(ScoreComponent, opportunity_id=opportunity.id)
        opportunity.evaluation_history = [
            *opportunity.evaluation_history,
            {
                "at": now().isoformat(),
                "score": opportunity.score,
                "score_version": opportunity.score_version,
                "score_inputs": opportunity.score_inputs,
                "components": [part.model_dump(mode="json") for part in parts],
                "audit_status": opportunity.audit_status,
                "facts": opportunity.facts,
                "qualification": opportunity.qualification,
                "note": "New source evidence; explicit commercial re-evaluation",
            },
        ]
        research = {"need": 0.75, "mandate_value": 0.4, "qualification": signal.qualification}
        scoring = score_opportunity(
            definition, opportunity.vertical_id, company, evidence, research, self.kb, self.as_of
        )
        status, reasons, confidence = audit_evidence(
            evidence, definition, self.as_of, opportunity.inferences, self.kb, live=True
        )
        opportunity.score, opportunity.score_version = scoring["score"], scoring["score_version"]
        opportunity.score_inputs = scoring["inputs"]
        opportunity.audit_status, opportunity.audit_reasons, opportunity.confidence = (
            cast(Literal["VERIFIED", "NEEDS_RESEARCH", "INSUFFICIENT_EVIDENCE", "REJECTED"], status.value),
            reasons,
            confidence,
        )
        opportunity.score_band = (
            scoring["score_band"] if status == "VERIFIED" else "IGNORE" if status == "REJECTED" else "MONITOR"
        )
        opportunity.trigger = (
            "External service requirement: " + self.kb.verticals[opportunity.vertical_id].name
        )
        opportunity.commercial_thesis = "A published external requirement warrants scope and eligibility review. Budget, appointment and engagement remain unconfirmed."
        opportunity.facts = [
            Claim(type=AssertionType.FACT, text=e.snippet, evidence_ids=[e.id]).model_dump(mode="json")
            for e in evidence
            if e.assertion_type == "FACT" and e.company_match and not e.conflict
        ]
        for part in parts:
            value = scoring["components"][part.name]
            part.points, part.maximum, part.rationale = value["points"], value["maximum"], value["rationale"]

    async def _research_candidate(self, candidate: dict, metrics: dict):
        signal = self.db.get(CompanySignal, candidate["company_signal_id"])
        assert signal is not None
        candidate_company = self.db.get(Company, signal.company_id)
        assert candidate_company is not None
        definition = self.kb.signals[signal.signal_key]
        vertical = self.kb.verticals[candidate["vertical_id"]]
        evidence = evidence_for(self.db, signal.evidence_ids)
        preferred = definition.possible_services if vertical.id == definition.vertical_ids[0] else None
        try:
            if self.research_failure:
                raise ProviderError(self.research_failure, retryable=False)
            services = await self.executor.call(
                partial(
                    self.kb.retrieve_services,
                    vertical.id,
                    definition.description,
                    self.providers.embeddings,
                    preferred,
                )
            )
        except ProviderError as error:
            if self.providers.llm.name != "openai":
                raise
            self.research_failure = error.code
            services = await self.kb.retrieve_services(
                vertical.id, definition.description, MockEmbeddingProvider(), preferred
            )
        context = {
            "vertical": vertical.model_dump(),
            "signal": definition.model_dump(),
            "evidence_ids": signal.evidence_ids,
            "retrieved_services": services,
            "company": candidate_company.canonical_name,
            "evidence": [e.model_dump(mode="json") for e in evidence],
        }
        try:
            if self.research_failure:
                raise ProviderError(self.research_failure, retryable=False)
            response = await self.executor.call(partial(self.providers.llm.research, context))
        except ProviderError as error:
            if self.providers.llm.name != "openai":
                raise
            self.research_failure = error.code
            candidate["provider_error"] = error.code
            metrics["errors"] += 1
            response = await MockLLMProvider().research(context)
            self.db.add(
                AuditLog(
                    module="research_fallback",
                    input_ref=candidate["company_signal_id"],
                    provider="openai",
                    success=False,
                    error=error.code,
                )
            )
        candidate["research"] = ResearchOutput.model_validate(response).model_dump(mode="json")
        if candidate.get("qualification"):
            q = candidate["qualification"]
            candidate["research"]["qualification"] = q
            candidate["research"]["need"] = 0.75 if q["service_demand"] else 0.15
            candidate["research"]["mandate_value"] = 0.4  # Stated scope, no assumed budget.
            q["llm_review"] = (
                "ASSISTED"
                if self.providers.llm.name == "openai" and not candidate.get("provider_error")
                else "NOT_REQUESTED"
            )
            if not candidate["research"].get("commercial_thesis"):
                candidate["research"]["commercial_thesis"] = (
                    "A published external service requirement warrants eligibility and scope review. Budget, appointment and engagement remain unconfirmed."
                )

        candidate["service"] = services[0]

    async def _store(
        self, candidate: dict, company: Company, signal: CompanySignal, evidence: list[Evidence]
    ) -> str:
        vertical = self.kb.verticals[candidate["vertical_id"]]
        definition = self.kb.signals[signal.signal_key]
        research, scoring, audit = candidate["research"], candidate["scoring"], candidate["audit"]
        facts = [
            Claim(type=AssertionType.FACT, text=e.snippet, evidence_ids=[e.id]).model_dump(mode="json")
            for e in evidence
            if e.assertion_type == "FACT"
        ]
        allegations = [
            Claim(type=AssertionType.ALLEGATION, text=e.snippet, evidence_ids=[e.id]).model_dump(mode="json")
            for e in evidence
            if e.assertion_type == "ALLEGATION"
        ]
        service = self.db.first(Service, vertical_id=vertical.id, name=candidate["service"])
        assert service is not None
        verified = audit["status"] == "VERIFIED"
        has_service_demand = bool(candidate.get("qualification", {}).get("service_demand"))
        band: Literal["HOT", "STRONG", "MONITOR", "IGNORE"] = (
            scoring["score_band"]
            if (verified or has_service_demand)
            else ("IGNORE" if audit["status"] == "REJECTED" else "MONITOR")
        )
        opportunity = Opportunity(
            company_id=company.id,
            company_signal_id=signal.id,
            record_origin=signal.record_origin,
            provenance={"source_ids": signal.evidence_ids},
            qualification=candidate.get("qualification", {}),
            score_inputs=scoring.get("inputs", {}),
            vertical_id=vertical.id,
            service_id=service.id,
            trigger=("External service requirement: " + vertical.name)
            if candidate.get("qualification")
            else definition.description,
            trigger_date=signal.event_date,
            facts=facts,
            allegations=allegations,
            inferences=research["inferences"],
            commercial_thesis=research["commercial_thesis"],
            why_now=research["why_now"],
            outreach_angle=research["outreach_angle"],
            score=scoring["score"],
            score_band=band,
            confidence=audit["confidence"],
            audit_status=audit["status"],
            audit_reasons=audit["reasons"],
            human_status="PENDING_REVIEW" if (verified or has_service_demand) else "NEEDS_RESEARCH",
            score_version=scoring["score_version"],
            knowledge_version=vertical.version,
            signal_version=definition.version,
        )
        self.db.add(opportunity)
        self.db.flush()
        if (verified or has_service_demand) and opportunity.score >= 80:
            self.db.add(
                HumanReviewTask(
                    opportunity_id=opportunity.id,
                    status="PENDING_REVIEW",
                    reason="Verified evidence and deterministic score >= 80"
                    if verified
                    else "Commercial service demand and deterministic score >= 80",
                )
            )
        candidate["opportunity_id"] = opportunity.id
        for e in evidence:
            self.db.add(OpportunityEvidence(opportunity_id=opportunity.id, document_id=e.id))
        for name, part in scoring["components"].items():
            self.db.add(ScoreComponent(opportunity_id=opportunity.id, name=name, **part))
        suggested_roles = [
            r for r in definition.possible_buyers if r in vertical.buyer_roles
        ] + vertical.buyer_roles
        roles = await self.executor.call(
            lambda: self.providers.contacts.roles(
                {"company_id": company.id, "name": company.canonical_name}, suggested_roles
            )
        )
        for role in roles:
            self.db.add(
                DecisionMakerRole(
                    opportunity_id=opportunity.id,
                    role=role,
                    rationale="Role-level recommendation from the matched vertical; no personal contact verified",
                )
            )
        if (verified or has_service_demand) and facts:
            fact = next(
                (e for e in evidence if e.assertion_type == "FACT" and e.company_match and not e.conflict),
                next((e for e in evidence if e.assertion_type == "FACT"), evidence[0]),
            )
            draft = OutreachDraft(
                opportunity_id=opportunity.id,
                subjects=[
                    f"{company.canonical_name}: {service.name}",
                    f"A question about your {definition.name.lower()}",
                ],
                body=f"Hello,\n\nYour published announcement states: {fact.snippet}\n\n"
                f"Novation supports {service.name.lower()}. Would a brief conversation about your team's priorities be useful?\n\n"
                "Best,\nNovation Strategy\n\n[Draft — human review required; no email will be sent]",
                verified_fact_ids=[fact.id],
            )
            if hasattr(self.providers.llm, "draft"):
                try:
                    draft_method = self.providers.llm.draft
                    evidence_subset = [
                        e
                        for e in evidence
                        if e.assertion_type == "FACT" and e.company_match and not e.conflict
                    ] or [fact]
                    generated = await self.executor.call(
                        lambda: draft_method(
                            {
                                "company": company.canonical_name,
                                "service": service.name,
                                "evidence_ids": [e.id for e in evidence_subset],
                                "evidence": [e.model_dump(mode="json") for e in evidence_subset],
                            }
                        )
                    )
                    draft.subjects, draft.body = generated.subjects, generated.body
                    draft.verified_fact_ids = generated.verified_fact_ids
                    draft.generation_version = self.providers.llm.model
                except ProviderError as error:
                    self.db.add(
                        AuditLog(
                            module="outreach_draft",
                            input_ref=opportunity.id,
                            provider="openai",
                            success=False,
                            error=error.code,
                        )
                    )
            self.db.add(draft)
        self.db.flush()
        return opportunity.id
