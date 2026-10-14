import asyncio
import logging
import re
from collections import Counter
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from leados.config import settings
from leados.knowledge import knowledge
from leados.pipeline import STAGES, Pipeline, evidence_for
from leados.providers.base import ProviderError
from leados.providers.cache import provider_cache
from leados.providers.factory import get_providers
from leados.providers.future.exa import ExaSearchProvider
from leados.providers.future.hubspot import HubSpotCRMProvider
from leados.safety import guarded_send, is_suppressed
from leados.schemas import (
    AuditStatus,
    CompanyRunInput,
    ExaAgentInput,
    ExaSearchInput,
    FeedbackInput,
    HumanStatus,
    LiveDiscoveryInput,
    OpportunityOutput,
    ReviewInput,
    RunInput,
    ScorePart,
    SuppressionInput,
)
from leados.services.connections import check_connections, connection_status
from leados.services.contact_enrichment import enrich_contacts, require_live_lead
from leados.services.discovery_jobs import discovery_jobs
from leados.services.identity import company_dedup_key, document_heading
from leados.services.live_activation import live_readiness
from leados.services.live_discovery import LiveDiscoveryService
from leados.services.master_view_sync import application_storage, master_view_status, sync_master_view
from leados.services.prospects import live_prospects
from leados.services.provenance import DataMode, qualified_opportunity, visible
from leados.services.search_intelligence import compute_search_intelligence
from leados.storage.base import StorageError, StorageProvider
from leados.storage.factory import api_write_lock, get_db, runtime_storage
from leados.storage.records import (
    AuditLog,
    Company,
    CompanyAlias,
    ContactEvent,
    DecisionMakerRole,
    FeedbackEvent,
    HumanReview,
    HumanReviewTask,
    Opportunity,
    OpportunityEvidence,
    OutreachDraft,
    ProviderRun,
    ScoreComponent,
    Service,
    Suppression,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    with application_storage(runtime_storage(), refresh=True, force_sync=True) as db:
        knowledge.seed(db)
    yield


cors_list = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
for default_origin in [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "*",
]:
    if default_origin not in cors_list:
        cors_list.append(default_origin)

app = FastAPI(title="Novation LeadOS", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_list,
    allow_origin_regex=r"https://.*\.onrender\.com",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def master_view_response_status(request: Request, call_next):
    response = await call_next(request)
    outcome = getattr(request.state, "master_view_outcome", None)
    if outcome:
        response.headers["X-LeadOS-Master-View"] = "pending" if outcome.get("pending") else "synced"
    return response


def required(db: StorageProvider, model, oid: str):
    record = db.get(model, oid)
    if record is None:
        raise HTTPException(404, "Record not found")
    return record


def record_dict(record) -> dict:
    return record.model_dump(mode="json")


def company_output(db: StorageProvider, company: Company) -> dict:
    return {
        **record_dict(company),
        "company_id": company.id,
        "aliases": [r.name for r in db.list(CompanyAlias, company_id=company.id)],
        "suppressed": is_suppressed(db, company.id),
        "contact_history": [record_dict(e) for e in db.list(ContactEvent, company_id=company.id)],
    }


def suppression_flags(db: StorageProvider, company_id: str) -> dict[str, bool]:
    record = db.first(Suppression, company_id=company_id)
    return {key: bool(record and getattr(record, key)) for key in ["do_not_contact", "opted_out", "bounced"]}


def opportunity_output(db: StorageProvider, opportunity: Opportunity) -> OpportunityOutput:
    company = required(db, Company, opportunity.company_id)
    service = required(db, Service, opportunity.service_id)
    evidence_ids = [r.document_id for r in db.list(OpportunityEvidence, opportunity_id=opportunity.id)]
    components = db.list(ScoreComponent, opportunity_id=opportunity.id)
    roles = list(dict.fromkeys(r.role for r in db.list(DecisionMakerRole, opportunity_id=opportunity.id)))
    draft = db.first(OutreachDraft, opportunity_id=opportunity.id)
    action = {"HOT": "Immediate BD review", "STRONG": "Review", "MONITOR": "Monitor", "IGNORE": "Ignore"}[
        opportunity.score_band
    ]
    if opportunity.audit_status != "VERIFIED" and not opportunity.qualification.get("service_demand"):
        action = "Research required" if opportunity.audit_status != "REJECTED" else "Reject"
    return OpportunityOutput(
        id=opportunity.id,
        record_origin=opportunity.record_origin,
        qualification=opportunity.qualification,
        score_inputs=opportunity.score_inputs,
        company_id=company.id,
        company=company.canonical_name,
        sector=company.sector,
        country=company.country,
        location=", ".join(company.locations),
        vertical_id=opportunity.vertical_id,
        vertical_name=knowledge.verticals[opportunity.vertical_id].name,
        opportunity_type=opportunity.trigger,
        trigger=opportunity.trigger,
        trigger_date=opportunity.trigger_date,
        age_days=(date.today() - opportunity.trigger_date).days if opportunity.trigger_date else None,
        facts=opportunity.facts,
        allegations=opportunity.allegations,
        inferences=opportunity.inferences,
        commercial_thesis=opportunity.commercial_thesis,
        evidence=evidence_for(db, evidence_ids),
        novation_service=service.name,
        why_now=opportunity.why_now,
        decision_maker_roles=roles,
        score_components={
            c.name: ScorePart(points=c.points, maximum=c.maximum, rationale=c.rationale) for c in components
        },
        score=opportunity.score,
        score_band=opportunity.score_band,
        confidence=opportunity.confidence,
        audit_status=AuditStatus(opportunity.audit_status),
        audit_reasons=opportunity.audit_reasons,
        recommended_action=action,
        outreach_angle=opportunity.outreach_angle,
        human_status=HumanStatus(opportunity.human_status),
        score_version=opportunity.score_version,
        knowledge_version=opportunity.knowledge_version,
        signal_version=opportunity.signal_version,
        created_at=opportunity.created_at,
        updated_at=opportunity.updated_at,
        draft=record_dict(draft) if draft else None,
        reviews=[
            record_dict(r)
            for r in sorted(db.list(HumanReview, opportunity_id=opportunity.id), key=lambda r: r.created_at)
        ],
        feedback=[
            record_dict(r)
            for r in sorted(db.list(FeedbackEvent, opportunity_id=opportunity.id), key=lambda r: r.created_at)
        ],
        contact_history=[
            record_dict(r)
            for r in sorted(db.list(ContactEvent, company_id=company.id), key=lambda r: r.created_at)
        ],
        suppressed=is_suppressed(db, company.id),
        suppression_flags=suppression_flags(db, company.id),
        email_send_enabled=False,
    )


@app.get("/health")
@app.get("/healthz")
def health(db: StorageProvider = Depends(get_db, scope="function")):
    db.health()
    return {
        "status": "ok",
        "mode": settings.leados_mode,
        "email_send_enabled": False,
        "verticals": len(knowledge.verticals),
        "signals": len(knowledge.signals),
    }


@app.get("/verticals")
def verticals():
    return list(knowledge.verticals.values())


@app.get("/signals")
def signals(vertical: str | None = None):
    return [s for s in knowledge.signals.values() if vertical is None or vertical in s.vertical_ids]


def run_output(run: ProviderRun) -> dict:
    metrics = run.metrics if isinstance(run.metrics, dict) else {}
    state = run.state if isinstance(run.state, dict) else {}
    return {
        "run_id": run.id,
        "status": run.status,
        "stage": run.stage,
        "metrics": {
            "opportunities_created": metrics.get("opportunities_created", 0),
            "duplicates_avoided": metrics.get("duplicates_avoided", 0),
            "errors": metrics.get("errors", 0),
            **metrics,
        },
        "duration_ms": run.duration_ms or 0,
        "error": run.error,
        "opportunity_ids": state.get("opportunity_ids", []),
        "human_review_ids": state.get("human_review_ids", []),
    }


@app.post("/pipeline/process")
@app.post("/pipeline/run")
async def pipeline_run(body: RunInput = RunInput(), db: StorageProvider = Depends(get_db, scope="function")):
    return run_output(await Pipeline(db).run(body.company))


@app.post("/pipeline/run/company")
async def company_run(body: CompanyRunInput, db: StorageProvider = Depends(get_db, scope="function")):
    return run_output(await Pipeline(db).run(body.company))


@app.post("/pipeline/start")
def pipeline_start(body: RunInput = RunInput(), db: StorageProvider = Depends(get_db, scope="function")):
    return run_output(Pipeline(db).start(body.company))


@app.post("/pipeline/runs/{run_id}/{stage}")
async def pipeline_stage(run_id: str, stage: str, db: StorageProvider = Depends(get_db, scope="function")):
    if stage not in STAGES:
        raise HTTPException(404, "Unknown pipeline stage")
    run = required(db, ProviderRun, run_id)
    try:
        result = await Pipeline(db).advance(run, stage)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return run_output(result)


@app.get("/pipeline/runs")
def pipeline_runs(db: StorageProvider = Depends(get_db, scope="function")):
    return [
        run_output(r) for r in sorted(db.list(ProviderRun), key=lambda r: r.created_at, reverse=True)[:50]
    ]


@app.post("/pipeline/runs/{run_id}/review-tasks/create")
def create_review_tasks(run_id: str, db: StorageProvider = Depends(get_db, scope="function")):
    run = required(db, ProviderRun, run_id)
    if run.status not in {"COMPLETED", "PARTIAL"}:
        raise HTTPException(409, "Complete the pipeline before creating review tasks")
    tasks = []
    for oid in run.state.get("human_review_ids", []):
        opportunity = required(db, Opportunity, oid)
        if opportunity.score < 80 or opportunity.audit_status != "VERIFIED":
            continue
        task = db.first(HumanReviewTask, opportunity_id=oid)
        if task is None:
            task = HumanReviewTask(
                opportunity_id=oid,
                status=opportunity.human_status,
                reason="Verified evidence and deterministic score >= 80",
            )
            db.add(task)
            db.flush()
        tasks.append(record_dict(task))
    return {"run_id": run_id, "tasks": tasks, "email_sent": False}


@app.get("/companies")
def companies(db: StorageProvider = Depends(get_db, scope="function"), data_mode: DataMode = "LIVE"):
    return [
        company_output(db, c)
        for c in sorted(db.list(Company), key=lambda c: c.canonical_name)
        if visible(c, data_mode)
    ]


@app.get("/companies/{company_id}")
def company_detail(company_id: str, db: StorageProvider = Depends(get_db, scope="function")):
    return company_output(db, required(db, Company, company_id))


@app.post("/companies/{company_id}/suppression")
def suppression(
    company_id: str, body: SuppressionInput, db: StorageProvider = Depends(get_db, scope="function")
):
    required(db, Company, company_id)
    record = db.first(Suppression, company_id=company_id)
    if record is None:
        record = Suppression(company_id=company_id, **body.model_dump(exclude_unset=True))
        db.add(record)
    else:
        for key, value in body.model_dump(exclude_unset=True).items():
            setattr(record, key, value)
    db.add(AuditLog(module="suppression", input_ref=company_id, output_ref=company_id, success=True))
    db.flush()
    return company_output(db, required(db, Company, company_id))


@app.get("/opportunities", response_model=list[OpportunityOutput])
def opportunities(
    data_mode: DataMode = "LIVE",
    vertical: str | None = None,
    min_score: int = Query(0, ge=0, le=100),
    status: HumanStatus | None = None,
    industry: str | None = None,
    country: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: StorageProvider = Depends(get_db, scope="function"),
):
    rows = []
    for opportunity in db.list(Opportunity):
        if not qualified_opportunity(opportunity, data_mode):
            continue
        company = db.get(Company, opportunity.company_id)
        if company is None or opportunity.score < min_score:
            continue
        if vertical and opportunity.vertical_id != vertical:
            continue
        if status and opportunity.human_status != status:
            continue
        if industry and company.sector != industry:
            continue
        if country and company.country != country:
            continue
        if date_from and (not opportunity.trigger_date or opportunity.trigger_date < date_from):
            continue
        if date_to and (not opportunity.trigger_date or opportunity.trigger_date > date_to):
            continue
        rows.append(opportunity)
    rows.sort(key=lambda o: (-o.score, o.id))
    return [opportunity_output(db, o) for o in rows[offset : offset + limit]]


@app.get("/opportunities/{opportunity_id}", response_model=OpportunityOutput)
def opportunity_detail(opportunity_id: str, db: StorageProvider = Depends(get_db, scope="function")):
    return opportunity_output(db, required(db, Opportunity, opportunity_id))


def review(
    db: StorageProvider,
    oid: str,
    decision: Literal["APPROVED", "REJECTED", "NEEDS_RESEARCH", "MONITOR"],
    body: ReviewInput,
):
    opportunity = required(db, Opportunity, oid)
    if (
        decision == "APPROVED"
        and opportunity.record_origin != "MOCK"
        and not qualified_opportunity(opportunity)
    ):
        raise HTTPException(409, "Verified buyer demand is required before live approval")
    if (
        decision == "APPROVED"
        and opportunity.audit_status != "VERIFIED"
        and not opportunity.qualification.get("service_demand")
    ):
        raise HTTPException(409, "Supporting evidence must be verified before approval")
    if decision == "APPROVED" and is_suppressed(db, opportunity.company_id):
        raise HTTPException(409, "Company is suppressed")
    opportunity.human_status = decision
    if opportunity.qualification:
        opportunity.qualification = {**opportunity.qualification, "human_review": decision}
    from leados.storage.records import now

    opportunity.updated_at = now()
    draft = db.first(OutreachDraft, opportunity_id=oid)
    if draft:
        draft.human_approved = decision == "APPROVED"
        draft.approved_by = body.reviewer if decision == "APPROVED" else ""
        draft.approved_at = now() if decision == "APPROVED" else None
    task = db.first(HumanReviewTask, opportunity_id=oid)
    if task:
        task.status = decision
    db.add(HumanReview(opportunity_id=oid, reviewer=body.reviewer, decision=decision, notes=body.notes))
    db.add(AuditLog(module="human_review", input_ref=oid, output_ref=oid, success=True))
    db.flush()
    return opportunity_output(db, opportunity)


@app.post("/opportunities/{opportunity_id}/approve", response_model=OpportunityOutput)
def approve(opportunity_id: str, body: ReviewInput, db: StorageProvider = Depends(get_db, scope="function")):
    return review(db, opportunity_id, "APPROVED", body)


@app.post("/opportunities/{opportunity_id}/reject", response_model=OpportunityOutput)
def reject(opportunity_id: str, body: ReviewInput, db: StorageProvider = Depends(get_db, scope="function")):
    return review(db, opportunity_id, "REJECTED", body)


@app.post("/opportunities/{opportunity_id}/research", response_model=OpportunityOutput)
def research(opportunity_id: str, body: ReviewInput, db: StorageProvider = Depends(get_db, scope="function")):
    return review(db, opportunity_id, "NEEDS_RESEARCH", body)


@app.post("/opportunities/{opportunity_id}/feedback", response_model=OpportunityOutput)
def feedback(
    opportunity_id: str, body: FeedbackInput, db: StorageProvider = Depends(get_db, scope="function")
):
    opportunity = required(db, Opportunity, opportunity_id)
    db.add(
        FeedbackEvent(
            opportunity_id=opportunity_id,
            **body.model_dump(),
            score_snapshot=opportunity.score,
            score_version=opportunity.score_version,
            knowledge_version=opportunity.knowledge_version,
            signal_version=opportunity.signal_version,
        )
    )
    if body.status == "Contacted":
        db.add(
            ContactEvent(
                company_id=opportunity.company_id,
                opportunity_id=opportunity_id,
                status="Contacted",
                channel="manually_reported",
            )
        )
    db.add(AuditLog(module="feedback", input_ref=opportunity_id, output_ref=opportunity_id, success=True))
    db.flush()
    return opportunity_output(db, opportunity)


@app.post("/opportunities/{opportunity_id}/send")
async def send(opportunity_id: str, db: StorageProvider = Depends(get_db, scope="function")):
    opportunity = required(db, Opportunity, opportunity_id)
    try:
        await guarded_send(db, opportunity, "", settings, get_providers().email)
    except ProviderError as exc:
        raise HTTPException(403, {"code": exc.code, "message": "No email sent"}) from exc


@app.get("/dashboard/today", response_model=list[OpportunityOutput])
def dashboard_today(db: StorageProvider = Depends(get_db, scope="function"), data_mode: DataMode = "LIVE"):
    # Today's review queue is based on discovery time; event date remains a separate filter.
    return [
        opportunity_output(db, o)
        for o in sorted(db.list(Opportunity), key=lambda o: -o.score)
        if qualified_opportunity(o, data_mode) and o.created_at.date() == date.today()
    ]


@app.get("/dashboard/metrics")
def dashboard_metrics(db: StorageProvider = Depends(get_db, scope="function"), data_mode: DataMode = "LIVE"):
    if data_mode == "LIVE":
        company_rows: dict[str, Opportunity] = {}
        for o in sorted(db.list(Opportunity), key=lambda item: (-item.score, item.id)):
            if qualified_opportunity(o, data_mode) and o.company_id not in company_rows:
                company_rows[o.company_id] = o
        rows = list(company_rows.values())
    else:
        rows = [o for o in db.list(Opportunity) if qualified_opportunity(o, data_mode)]
    runs = (
        [r for r in db.list(ProviderRun) if r.provider == "exa+firecrawl"]
        if data_mode == "LIVE"
        else [
            r
            for r in db.list(ProviderRun)
            if r.provider == "provider_bundle" and not r.state.get("live_documents")
        ]
    )
    return {
        "companies": sum(
            visible(c, data_mode) and (data_mode != "LIVE" or not document_heading(c.canonical_name))
            for c in db.list(Company)
        ),
        "data_mode": data_mode,
        "unqualified_live_signals": sum(
            visible(o, data_mode) and not qualified_opportunity(o, data_mode) for o in db.list(Opportunity)
        ),
        "opportunities": len(rows),
        "hot": sum(o.score_band == "HOT" and o.audit_status == "VERIFIED" for o in rows),
        "pending_review": sum(o.human_status == "PENDING_REVIEW" for o in rows),
        "needs_research": sum(
            o.audit_status != "VERIFIED" or o.human_status == "NEEDS_RESEARCH" for o in rows
        ),
        "average_score": round(sum(o.score for o in rows) / len(rows), 1) if rows else 0,
        "by_vertical": dict(Counter(o.vertical_id for o in rows)),
        "by_band": dict(Counter(o.score_band for o in rows)),
        "pipeline_runs": len(runs),
        "duplicates_avoided": sum(
            (r.metrics or {}).get("duplicates_avoided", 0) for r in runs if isinstance(r.metrics, dict)
        ),
        "errors": sum((r.metrics or {}).get("errors", 0) for r in runs if isinstance(r.metrics, dict)),
        "rejections": sum(
            (r.metrics or {}).get("rejections", 0) for r in runs if isinstance(r.metrics, dict)
        ),
        "processing_ms": sum((r.duration_ms or 0) for r in runs),
        "email_send_enabled": False,
    }


@app.exception_handler(StorageError)
async def storage_failure(request: Request, exc: StorageError):
    return JSONResponse(
        status_code=503,
        content={
            "detail": {
                "code": exc.code,
                "message": exc.detail or "Storage operation failed; no credentials exposed",
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logging.exception("Unhandled error processing %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Check server logs."},
    )


@app.get("/dashboard/state")
def dashboard_state(db: StorageProvider = Depends(get_db, scope="function"), data_mode: DataMode = "LIVE"):
    """Return one committed revision and compact rows, without full lead dossiers."""
    companies = {company.id: company for company in db.list(Company)}
    services = {service.id: service for service in db.list(Service)}
    rows = []
    seen_companies = set()
    for opportunity in sorted(db.list(Opportunity), key=lambda item: (-item.score, item.id)):
        if not qualified_opportunity(opportunity, data_mode):
            continue
        company = companies.get(opportunity.company_id)
        service = services.get(opportunity.service_id)
        if company is None or service is None:
            continue
        if data_mode == "LIVE":
            if company.id in seen_companies:
                continue
            seen_companies.add(company.id)
        rows.append(
            {
                "id": opportunity.id,
                "company_id": company.id,
                "company": company.canonical_name,
                "sector": company.sector,
                "country": company.country,
                "vertical_id": opportunity.vertical_id,
                "vertical_name": knowledge.verticals[opportunity.vertical_id].name,
                "trigger": opportunity.trigger,
                "trigger_date": opportunity.trigger_date,
                "age_days": (date.today() - opportunity.trigger_date).days
                if opportunity.trigger_date
                else None,
                "novation_service": service.name,
                "score": opportunity.score,
                "score_band": opportunity.score_band,
                "confidence": opportunity.confidence,
                "audit_status": opportunity.audit_status,
                "human_status": opportunity.human_status,
                "created_at": opportunity.created_at,
                "suppressed": is_suppressed(db, company.id),
            }
        )
    prospects = live_prospects(db) if data_mode == "LIVE" else []
    return {
        "verticals": list(knowledge.verticals.values()),
        "opportunities": rows,
        "metrics": dashboard_metrics(db, data_mode),
        "data_mode": data_mode,
        "discovery_results": live_discovery_results(db, prospects_list=prospects) if data_mode == "LIVE" else [],
        "prospects": prospects,
    }


@app.get("/prospects/{prospect_id}")
def prospect_detail(prospect_id: str, db: StorageProvider = Depends(get_db, scope="function")):
    for prospect in live_prospects(db):
        if prospect["id"] == prospect_id:
            return prospect
    raise HTTPException(404, "Research prospect not found")


@app.get("/storage/health")
async def storage_health():
    async with api_write_lock:
        try:
            with runtime_storage().transaction(refresh=True) as storage:
                return storage.health()
        except StorageError as exc:
            return {
                "provider": settings.leados_storage,
                "connected": False,
                "spreadsheet_accessible": False,
                "tabs_valid": False,
                "error": {"code": exc.code, "message": exc.detail},
            }


@app.post("/storage/master-view/sync")
async def sync_master_overview():
    async with api_write_lock:
        return sync_master_view(runtime_storage())


@app.get("/storage/master-view/status")
async def master_overview_status():
    async with api_write_lock:
        return master_view_status(runtime_storage())


@app.post("/opportunities/{opportunity_id}/monitor", response_model=OpportunityOutput)
def monitor(opportunity_id: str, body: ReviewInput, db: StorageProvider = Depends(get_db, scope="function")):
    return review(db, opportunity_id, "MONITOR", body)


@app.get("/discovery/exa/status")
def exa_status():
    """Return Exa provider configuration status and recommended request options."""
    configured = bool(settings.exa_api_key)
    return {
        "provider": "exa",
        "configured": configured,
        "search_provider": settings.search_provider,
        "model": "auto",
        "recommended_request": {
            "type": "auto",
            "contents": {"highlights": True},
        },
    }


@app.post("/discovery/exa/search")
async def exa_search_discovery(
    body: ExaSearchInput = ExaSearchInput(),
    db: StorageProvider = Depends(get_db, scope="function"),
):
    """Discover real-time corporate events, executive hiring, and business signals using Exa."""
    provider = ExaSearchProvider(enabled=True, num_results=body.num_results)
    try:
        documents = await provider.search(company=body.company)
    except ProviderError as exc:
        raise HTTPException(502, f"Exa search error: {exc}") from exc
    return {
        "provider": "exa",
        "query_target": body.company or "India executive hiring and expansion",
        "count": len(documents),
        "documents": documents,
    }


@app.post("/discovery/exa/agent")
async def exa_agent_research(
    body: ExaAgentInput,
):
    """Deep multi-step executive hiring research and enrichment via Exa Agent API (/agent/runs)."""
    provider = ExaSearchProvider(enabled=True)
    try:
        result = await provider.research_agent(query=body.query, effort=body.effort)
    except ProviderError as exc:
        raise HTTPException(502, f"Exa agent error: {exc}") from exc
    return result


@app.get("/providers/status")
def providers_status():
    return connection_status()


@app.post("/providers/check")
async def providers_check():
    return await check_connections()


@app.get("/opportunities/{opportunity_id}/contacts")
def contacts_for_opportunity(opportunity_id: str, db: StorageProvider = Depends(get_db, scope="function")):
    required(db, Opportunity, opportunity_id)
    return [
        record_dict(role)
        for role in db.list(DecisionMakerRole, opportunity_id=opportunity_id)
        if role.person_name
    ]


@app.post("/opportunities/{opportunity_id}/contacts/enrich")
async def contacts_enrich(opportunity_id: str, db: StorageProvider = Depends(get_db, scope="function")):
    try:
        return await enrich_contacts(db, required(db, Opportunity, opportunity_id))
    except ProviderError as error:
        raise HTTPException(409, error.code) from error


@app.post("/opportunities/{opportunity_id}/crm/sync")
async def sync_crm(opportunity_id: str, db: StorageProvider = Depends(get_db, scope="function")):
    opportunity = required(db, Opportunity, opportunity_id)
    try:
        company = require_live_lead(db, opportunity)
        reviews = sorted(
            db.list(HumanReview, opportunity_id=opportunity.id), key=lambda row: (row.created_at, row.id)
        )
        if opportunity.human_status != "APPROVED" or not reviews or reviews[-1].decision != "APPROVED":
            raise ProviderError("human_approval_required", retryable=False)
        previous = db.first(AuditLog, module="hubspot_sync", input_ref=opportunity.id, success=True)
        if previous:
            return {"status": "ALREADY_SYNCED", "company_id": previous.output_ref, "external_write": False}
        service = required(db, Service, opportunity.service_id)
        result = await HubSpotCRMProvider().sync(
            {
                "id": opportunity.id,
                "company": company.canonical_name,
                "domain": company.domain,
                "score": opportunity.score,
                "service": service.name,
                "thesis": opportunity.commercial_thesis,
                "status": "New",
            }
        )
        db.add(
            AuditLog(
                module="hubspot_sync",
                input_ref=opportunity.id,
                output_ref=result["company_id"],
                provider="hubspot",
                success=True,
            )
        )
        db.flush()
        return {**result, "email_sent": False}
    except ProviderError as error:
        raise HTTPException(409, error.code) from error


@app.get("/providers/exa/health")
def exa_health():
    configured = bool(settings.exa_api_key)
    enabled = settings.search_provider == "exa" or settings.live_discovery_enabled
    stats = provider_cache.get_stats()
    return {
        "provider": "exa",
        "configured": configured,
        "enabled": enabled,
        "daily_calls": stats.get("daily_exa_calls", 0),
        "max_daily_calls": settings.max_exa_calls_per_day,
        "last_success": stats.get("last_exa_success"),
        "last_error": stats.get("last_exa_error"),
    }


@app.get("/providers/firecrawl/health")
def firecrawl_health():
    configured = bool(settings.firecrawl_api_key)
    enabled = settings.crawler_provider == "firecrawl" or settings.live_discovery_enabled
    stats = provider_cache.get_stats()
    return {
        "provider": "firecrawl",
        "configured": configured,
        "enabled": enabled,
        "daily_calls": stats.get("daily_firecrawl_calls", 0),
        "max_daily_calls": settings.max_firecrawl_calls_per_day,
        "last_success": stats.get("last_firecrawl_success"),
        "last_error": stats.get("last_firecrawl_error"),
    }


@app.post("/pipeline/discover/live/estimate")
def live_discovery_estimate(
    body: LiveDiscoveryInput = LiveDiscoveryInput(),
):
    service = LiveDiscoveryService()
    estimate = service.estimate(
        verticals=body.verticals,
        max_queries=body.max_queries,
        dry_run=body.dry_run,
        max_companies=body.max_companies,
        query_offset=body.query_offset,
    )
    return estimate.model_dump()


@app.get("/pipeline/discover/live/status")
def live_discovery_status():
    return live_readiness(settings, provider_cache)


@app.post("/pipeline/discover/live/jobs", status_code=202)
async def start_live_discovery_job(body: LiveDiscoveryInput = LiveDiscoveryInput()):
    for job in discovery_jobs.jobs.values():
        if job["status"] in {"QUEUED", "RUNNING", "SYNCING"}:
            return job
    is_dry = body.dry_run if body.dry_run is not None else settings.live_provider_dry_run
    if not is_dry:
        readiness = live_readiness(settings, provider_cache)
        if not readiness["ready"]:
            raise HTTPException(403, "; ".join(readiness["blockers"]))
    return discovery_jobs.start(body.model_copy(update={"dry_run": is_dry}))


@app.post("/pipeline/discover/live/jobs/{job_id}/stop")
def stop_live_discovery_job(job_id: str):
    if job_id not in discovery_jobs.jobs:
        raise HTTPException(404, "Discovery job not found")
    return discovery_jobs.stop(job_id)


@app.get("/pipeline/discover/live/jobs/latest")
def latest_live_discovery_job():
    return discovery_jobs.latest()


@app.get("/pipeline/discover/live/jobs/{job_id}")
def live_discovery_job(job_id: str):
    job = discovery_jobs.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Discovery job not found")
    return job


@app.post("/pipeline/discover/live/jobs/{job_id}/sync")
async def retry_discovery_sync(job_id: str):
    job = discovery_jobs.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Discovery job not found")
    if job["status"] in {"QUEUED", "RUNNING", "SYNCING"}:
        raise HTTPException(409, "This discovery run is still active")
    async with api_write_lock:
        await asyncio.to_thread(sync_master_view, runtime_storage())
        summary = job.get("summary") or {}
        updated = {
            **job,
            "sheets_synced": True,
            "status": summary.get("status", job["status"]),
            "error": summary.get("error"),
        }
        discovery_jobs.save(updated)
    return updated


_search_intel_cache: dict[str, dict] = {}


@app.get("/pipeline/discover/live/results")
def live_discovery_results(
    db: StorageProvider = Depends(get_db, scope="function"),
    limit: int = 50,
    prospects_list: list[dict] | None = None,
):
    runs = sorted(db.list(ProviderRun), key=lambda run: run.created_at, reverse=True)
    p_list = prospects_list if prospects_list is not None else live_prospects(db)
    prospects = {s["url"]: p for p in p_list for s in p["sources"]}
    db_companies = {c.id: company_dedup_key(c.canonical_name) for c in db.list(Company)}
    db_opps_by_comp_key: dict[str, list[str]] = {}
    for o in db.list(Opportunity):
        if o.record_origin == "LIVE":
            k = db_companies.get(o.company_id, "")
            if k:
                db_opps_by_comp_key.setdefault(k, []).append(o.id)

    results = []
    seen_company_map = {}
    for run in runs:
        if "discovery_results" not in run.state or run.provider != "exa+firecrawl":
            continue
        for saved in run.state["discovery_results"]:
            if saved.get("record_origin") != "LIVE":
                continue
            company_name = saved.get("company", "").strip()
            if not company_name or document_heading(company_name):
                continue
            if re.search(r"\b(secretariat|ministry|department of)\b", company_name, re.IGNORECASE):
                continue
            ckey = company_dedup_key(company_name)
            if ckey in seen_company_map:
                existing_row = seen_company_map[ckey]
                if not existing_row.get("opportunity_ids"):
                    candidate_opps = saved.get("opportunity_ids") or saved.get("historical_opportunity_ids") or []
                    if candidate_opps:
                        existing_row["opportunity_ids"] = [candidate_opps[0]]
                other_url = saved.get("source_url")
                if other_url and other_url != existing_row.get("source_url"):
                    if "other_sources" not in existing_row:
                        existing_row["other_sources"] = []
                    if not any(s.get("source_url") == other_url for s in existing_row["other_sources"]):
                        existing_row["other_sources"].append({
                            "title": saved.get("title"),
                            "source_url": other_url,
                            "published_date": saved.get("published_date"),
                        })
                continue

            row = dict(saved)
            if not row.get("search_date") and run.created_at:
                row["search_date"] = str(run.created_at)[:10]
            prospect = prospects.get(row.get("source_url", ""))
            if prospect:
                row["prospect"] = {
                    key: prospect[key]
                    for key in ("id", "trigger", "vertical", "recommended_service", "research_status")
                }
            else:
                row.pop("prospect", None)
            row["identity_status"] = (
                "UNCONFIRMED" if document_heading(row.get("company", "")) else "SOURCE_REPORTED"
            )
            opp_ids = list(row.get("opportunity_ids") or row.get("historical_opportunity_ids") or [])
            if not opp_ids and ckey in db_opps_by_comp_key:
                opp_ids = db_opps_by_comp_key[ckey]
            # Each company represented strictly has one single dossier
            row["opportunity_ids"] = opp_ids[:1]
            si = row.get("search_intelligence")
            if not si or not isinstance(si, dict) or not si.get("total_factor_score"):
                cache_key = f"{ckey}:{row.get('source_url', '')}"
                if cache_key in _search_intel_cache:
                    row["search_intelligence"] = _search_intel_cache[cache_key]
                else:
                    computed = compute_search_intelligence(
                        db=db,
                        candidate=row,
                        qualification=row.get("qualification"),
                        opportunity_ids=row["opportunity_ids"],
                    )
                    _search_intel_cache[cache_key] = computed
                    row["search_intelligence"] = computed
            seen_company_map[ckey] = row
            results.append(row)
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break
    return results


@app.post("/pipeline/discover/live")
async def live_discovery_run(
    body: LiveDiscoveryInput = LiveDiscoveryInput(),
    db: StorageProvider = Depends(get_db, scope="function"),
):
    is_dry_run = body.dry_run if body.dry_run is not None else settings.live_provider_dry_run
    if not is_dry_run and not settings.live_discovery_enabled:
        raise HTTPException(
            403,
            "Live discovery is currently disabled (LIVE_DISCOVERY_ENABLED=false). "
            "Use dry_run=true to preview or enable in configuration.",
        )
    # get_db already holds the writer lock; acquiring it twice deadlocks.
    service = LiveDiscoveryService(db)
    summary = await service.run(
        verticals=body.verticals,
        max_queries=body.max_queries,
        dry_run=is_dry_run,
        cache_only=body.cache_only,
        company_filter=body.company,
        max_companies=body.max_companies,
        query_offset=body.query_offset,
    )
    return summary.model_dump()
