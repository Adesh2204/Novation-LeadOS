from datetime import date

import pytest

from leados.config import Settings
from leados.pipeline import STAGES, Pipeline
from leados.providers.base import ProviderError, ProviderExecutor, ProviderPolicy
from leados.providers.factory import get_providers
from leados.safety import guarded_send
from leados.storage.records import (
    AuditLog,
    Company,
    CompanySignal,
    ContactEvent,
    DecisionMakerRole,
    FeedbackEvent,
    HumanReview,
    Opportunity,
    OutreachDraft,
    Source,
    SourceDocument,
    Suppression,
)


def counts(db):
    return {
        name: len(db.list(model))
        for name, model in [
            ("companies", Company),
            ("sources", Source),
            ("source_documents", SourceDocument),
            ("company_signals", CompanySignal),
            ("opportunities", Opportunity),
        ]
    }


def by_company(db, name):
    company = db.first(Company, canonical_name=name)
    return db.list(Opportunity, company_id=company.id) if company else []


def mark_approved(db, opportunity):
    opportunity.human_status = "APPROVED"
    db.add(
        HumanReview(
            opportunity_id=opportunity.id,
            reviewer="Safety test",
            decision="APPROVED",
            notes="Verified synthetic data",
        )
    )
    draft = db.first(OutreachDraft, opportunity_id=opportunity.id)
    if draft:
        draft.human_approved = True
    role = db.first(DecisionMakerRole, opportunity_id=opportunity.id)
    role.person_name = "Synthetic test contact"
    role.contact_email = "synthetic@example.test"
    role.contact_status = "VALIDATED"
    role.contact_source = "synthetic test fixture"


async def test_discovery_is_idempotent_and_preserves_history(populated):
    before = counts(populated)
    opportunity = populated.first(Opportunity, audit_status="VERIFIED")
    opportunity.human_status = "APPROVED"
    populated.add(
        HumanReview(opportunity_id=opportunity.id, reviewer="Test", decision="APPROVED", notes="Keep")
    )
    populated.add(
        FeedbackEvent(
            opportunity_id=opportunity.id,
            status="Meeting",
            reason=None,
            notes="Keep",
            buyer_role="CFO",
            score_snapshot=opportunity.score,
            score_version=opportunity.score_version,
            knowledge_version=opportunity.knowledge_version,
            signal_version=opportunity.signal_version,
        )
    )
    populated.commit()
    run = await Pipeline(populated, as_of=date(2026, 10, 6)).run()
    assert counts(populated) == before
    assert before["companies"] == 40
    assert before["opportunities"] == 44
    assert run.metrics["opportunities_created"] == 0
    assert run.metrics["duplicates_avoided"] > 40
    assert populated.get(Opportunity, opportunity.id).human_status == "APPROVED"
    assert len(populated.list(FeedbackEvent)) == 1


async def test_all_verticals_and_safety_cases(populated):
    assert len({o.vertical_id for o in populated.list(Opportunity)}) == 9
    for name in ["Weak AI Rumors", "Undated Privacy Labs", "Conflicted Vendor Co", "Clearwater Holdings"]:
        opportunities = by_company(populated, name)
        assert opportunities
        assert all(
            o.score_band != "HOT" and o.audit_status == "NEEDS_RESEARCH" and o.confidence < 0.7
            for o in opportunities
        )
    for name in [
        "Quiet AI Media",
        "Funding Only Ventures",
        "New CFO Enterprises",
        "Denial AI Systems",
        "Empty Evidence Co",
    ]:
        assert not by_company(populated, name)
    alleged = by_company(populated, "Clearwater Holdings")[0]
    assert alleged.facts == [] and alleged.allegations[0]["type"] == "ALLEGATION"
    twin_names = populated.list(Company, canonical_name="Twin Name")
    assert len(twin_names) == 2 and twin_names[0].domain != twin_names[1].domain


async def test_staged_pipeline_idempotent_stage_and_order(db):
    pipeline = Pipeline(db, as_of=date(2026, 10, 6))
    run = pipeline.start("Atlas AI Systems")
    with pytest.raises(ValueError, match="stage_order"):
        await pipeline.advance(run, "store")
    for stage in STAGES:
        await pipeline.advance(run, stage)
        before = counts(db)
        await pipeline.advance(run, stage)
        assert counts(db) == before
    assert run.status == "PARTIAL"
    assert run.metrics["companies_discovered"] == 1
    assert len(run.state["human_review_ids"]) == 2


class SpyEmail:
    name = "spy"
    calls = 0

    async def send(self, opportunity_id, body):
        self.calls += 1
        raise AssertionError("Transport must never be reached")


async def test_cannot_reach_email_provider_without_approval(populated):
    opportunity = populated.first(Opportunity, audit_status="VERIFIED")
    spy = SpyEmail()
    with pytest.raises(ProviderError, match="human_approval_required"):
        await guarded_send(populated, opportunity, "", Settings(enable_email_send=True), spy)
    assert spy.calls == 0


async def test_approved_lead_disabled_flag_and_v1_hard_stop(populated):
    opportunity = populated.first(Opportunity, audit_status="VERIFIED")
    mark_approved(populated, opportunity)
    spy = SpyEmail()
    for enabled, code in [(False, "email_send_disabled"), (True, "email_transport_disabled_in_v1")]:
        with pytest.raises(ProviderError, match=code):
            await guarded_send(populated, opportunity, "", Settings(enable_email_send=enabled), spy)
    assert spy.calls == 0


@pytest.mark.parametrize("field", ["do_not_contact", "opted_out", "bounced"])
async def test_suppression_and_previous_contact(populated, field):
    opportunity = populated.first(Opportunity, audit_status="VERIFIED")
    mark_approved(populated, opportunity)
    populated.add(Suppression(company_id=opportunity.company_id, **{field: True}))
    populated.flush()
    spy = SpyEmail()
    with pytest.raises(ProviderError, match="company_suppressed"):
        await guarded_send(populated, opportunity, "", Settings(enable_email_send=True), spy)
    populated.first(Suppression, company_id=opportunity.company_id).active = False
    populated.add(
        ContactEvent(
            company_id=opportunity.company_id,
            opportunity_id=opportunity.id,
            status="Contacted",
            channel="manual",
        )
    )
    populated.flush()
    with pytest.raises(ProviderError, match="previous_contact_requires_review"):
        await guarded_send(populated, opportunity, "", Settings(enable_email_send=True), spy)
    assert spy.calls == 0


async def test_empty_search(db):
    run = await Pipeline(db).run("Company that is not in fixtures")
    assert run.status == "COMPLETED" and counts(db)["opportunities"] == 0


async def test_provider_failure_rolls_back_stage_and_records_safe_error(db):
    class Unavailable:
        name = "unavailable"

        async def search(self, company=None):
            raise ProviderError("secret-must-not-appear")

    providers = get_providers()
    providers.search = Unavailable()
    run = await Pipeline(db, providers).run()
    assert run.status == "FAILED"
    assert run.error == "provider_unavailable"
    assert counts(db)["opportunities"] == 0
    assert not any("secret" in (a.error or "") for a in db.list(AuditLog))


async def test_bad_llm_output_no_partial_opportunity_write(db):
    class BrokenLLM:
        name = "broken"
        model = "invalid-json"

        async def research(self, context):
            return {"invented_score": 100}

    providers = get_providers()
    providers.llm = BrokenLLM()
    run = await Pipeline(db, providers).run("Atlas AI Systems")
    assert run.status == "FAILED" and run.error == "ValidationError"
    assert counts(db)["opportunities"] == 0


async def test_storage_candidate_failure_preserves_other_successes(db, monkeypatch):
    from leados.storage.base import StorageError
    from leados.storage.records import ScoreComponent

    original = db.add
    calls = 0

    def fail_second(record):
        nonlocal calls
        if isinstance(record, Opportunity):
            calls += 1
            if calls == 2:
                raise StorageError("simulated_write_failure")
        return original(record)

    monkeypatch.setattr(db, "add", fail_second)
    run = await Pipeline(db).run("Atlas AI Systems")
    assert run.status == "PARTIAL"
    assert run.metrics["successful"] == 1 and run.metrics["failed"] == 1
    assert counts(db)["opportunities"] == 1
    assert len(db.list(ScoreComponent)) == 8
    monkeypatch.setattr(db, "add", original)
    recovered = await Pipeline(db).run("Atlas AI Systems")
    assert recovered.status == "PARTIAL" and recovered.metrics["opportunities_created"] == 1


async def test_retries_timeout_and_rate_limit():
    import asyncio

    executor = ProviderExecutor(ProviderPolicy(max_attempts=2, timeout_seconds=0.005, backoff_seconds=0))
    calls = 0

    async def transient():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ProviderError("retry", retry_after=0.001)
        return "ok"

    assert await executor.call(transient) == "ok" and calls == 2
    with pytest.raises(ProviderError, match="provider_unavailable"):
        await executor.call(lambda: asyncio.sleep(0.05))
    limited = ProviderExecutor(ProviderPolicy(requests_per_minute=1))
    assert await limited.call(transient) == "ok"
    with pytest.raises(ProviderError, match="rate_limit"):
        await limited.call(transient)
