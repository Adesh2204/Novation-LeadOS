from datetime import date, timedelta

import pytest

from leados.engine import (
    audit_evidence,
    canonical_url,
    detect_signals,
    digest,
    recency_factor,
    resolve_company,
    route_verticals,
    score_opportunity,
)
from leados.knowledge import knowledge
from leados.schemas import CompanyInput, Evidence
from leados.storage.records import now

ANCHOR = date(2026, 10, 6)


@pytest.mark.parametrize("sid", list(knowledge.signals))
def test_every_business_event_detects_and_routes(sid):
    signal = knowledge.signals[sid]
    assert detect_signals(signal.examples[0], knowledge.signals) == [sid]
    routes = route_verticals(signal)
    assert [r["vertical_id"] for r in routes] == signal.vertical_ids
    assert routes[0]["rank"] == 1


@pytest.mark.parametrize(
    "text",
    [
        "Company writes about AI",
        "Company raised Series B funding",
        "Company appoints a new CFO",
        "Company has not deployed an AI recruitment decision system.",
        "AI recruitment decision system: no operational change",
    ],
)
def test_false_positives(text):
    assert detect_signals(text, knowledge.signals) == []


@pytest.mark.parametrize(
    "age,factor",
    [(0, 1), (7, 1), (8, 0.8), (30, 0.8), (31, 0.5), (90, 0.5), (91, 0.2), (180, 0.2), (181, 0), (500, 0)],
)
def test_recency_boundaries(age, factor):
    assert recency_factor(ANCHOR - timedelta(days=age), ANCHOR, knowledge.scoring) == factor


def test_missing_and_future_dates():
    assert recency_factor(None, ANCHOR, knowledge.scoring) == 0
    assert recency_factor(ANCHOR + timedelta(days=1), ANCHOR, knowledge.scoring) == 0


def company_data(name="Atlas AI Systems", domain="atlas.example", country="India"):
    return CompanyInput(
        name=name,
        domain=domain,
        country=country,
        sector="SaaS",
        employee_range="201-500",
        funding_stage="Series B",
        locations=["Bengaluru"],
        description="Synthetic company",
    )


def test_entity_alias_same_domain(db):
    one, created = resolve_company(db, company_data())
    two, second_created = resolve_company(db, company_data("Atlas AI Systems Pvt Ltd", "www.atlas.example"))
    assert created and not second_created
    assert one.id == two.id
    assert two.merge_confidence == 1


def test_similar_names_different_domains_do_not_merge(db):
    one, _ = resolve_company(db, company_data())
    two, _ = resolve_company(db, company_data("Atlas AI System", "other-atlas.example"))
    assert one.id != two.id
    three, _ = resolve_company(db, company_data(domain="atlas.example", country="United Kingdom"))
    assert three.id != one.id


def test_exact_alias_without_domain_conservative(db):
    data = company_data(domain=None)
    data.aliases = ["Atlas Systems"]
    one, _ = resolve_company(db, data)
    two, _ = resolve_company(db, company_data("Atlas Systems", domain=None))
    assert one.id == two.id
    assert one.merge_confidence < 1


def test_non_latin_companies_do_not_collapse_to_empty_identity(db):
    one, _ = resolve_company(db, company_data("北京科技", domain=None))
    two, _ = resolve_company(db, company_data("上海科技", domain=None))
    assert one.id != two.id


def test_url_and_content_dedup():
    assert canonical_url("https://atlas.example/news?utm_source=ads#top") == "https://atlas.example/news"
    assert digest("same content") == digest("same content")
    with pytest.raises(ValueError):
        canonical_url("file:///etc/passwd")


def evidence(**overrides):
    data = dict(
        id="doc",
        source_url="https://atlas.example/news",
        source_name="Fixture newsroom",
        source_type="fixture_primary",
        published_date=ANCHOR,
        retrieved_at=now(),
        snippet="Atlas launches an AI recruitment decision system.",
        confidence=0.95,
        content_hash=digest("fixture"),
        assertion_type="FACT",
        company_match=True,
        conflict=False,
        language="en",
    )
    return Evidence(**{**data, **overrides})


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({}, "VERIFIED"),
        ({"confidence": 0.2}, "NEEDS_RESEARCH"),
        ({"published_date": None}, "NEEDS_RESEARCH"),
        ({"conflict": True}, "NEEDS_RESEARCH"),
        ({"company_match": False}, "REJECTED"),
        ({"assertion_type": "ALLEGATION"}, "NEEDS_RESEARCH"),
        ({"snippet": "Only AI discussion"}, "NEEDS_RESEARCH"),
        ({"published_date": ANCHOR + timedelta(days=1)}, "NEEDS_RESEARCH"),
    ],
)
def test_evidence_requirements(overrides, expected):
    status, _, confidence = audit_evidence(
        [evidence(**overrides)],
        knowledge.signals["AI_RECRUITMENT_SYSTEM"],
        ANCHOR,
        [{"evidence_ids": ["doc"]}],
        knowledge,
    )
    assert status == expected
    if expected != "VERIFIED":
        assert confidence < 0.7


def test_no_evidence_or_invented_references():
    signal = knowledge.signals["AI_RECRUITMENT_SYSTEM"]
    assert audit_evidence([], signal, ANCHOR, [], knowledge)[0] == "INSUFFICIENT_EVIDENCE"
    assert (
        audit_evidence([evidence()], signal, ANCHOR, [{"evidence_ids": ["invented"]}], knowledge)[0]
        == "NEEDS_RESEARCH"
    )


def test_deterministic_scoring_and_normalized_signal_weight(db):
    company, _ = resolve_company(db, company_data())
    signal = knowledge.signals["AI_RECRUITMENT_SYSTEM"]
    inputs = (
        signal,
        "ai_governance",
        company,
        [evidence()],
        {"need": 1, "mandate_value": 0.8},
        knowledge,
        ANCHOR,
    )
    result = score_opportunity(*inputs)
    assert result == score_opportunity(*inputs)
    assert result["score"] == 96
    assert result["components"]["trigger_strength"]["points"] == 20
    assert result["score"] == sum(p["points"] for p in result["components"].values())
    assert sum(p["maximum"] for p in result["components"].values()) == 100
    assert result["score_band"] == "HOT"


@pytest.mark.parametrize(
    "strength,need,age,sector,band",
    [
        (25, 1, 0, "SaaS", "HOT"),
        (20, 0.8, 200, "Other", "STRONG"),
        (12, 0.5, 200, "Other", "MONITOR"),
        (0, 0, 200, "Other", "IGNORE"),
    ],
)
def test_all_score_bands(db, strength, need, age, sector, band):
    company, _ = resolve_company(db, company_data())
    company.sector = sector
    signal = knowledge.signals["AI_RECRUITMENT_SYSTEM"].model_copy(update={"base_strength": strength})
    result = score_opportunity(
        signal,
        "ai_governance",
        company,
        [evidence(published_date=ANCHOR - timedelta(days=age))],
        {"need": need, "mandate_value": 0.8},
        knowledge,
        ANCHOR,
    )
    assert result["score_band"] == band


def test_knowledge_completeness():
    assert len(knowledge.verticals) == 9
    assert len(knowledge.signals) >= 100
    assert set(knowledge.verticals) == {v for s in knowledge.signals.values() for v in s.vertical_ids}
    assert all(
        len(s.description) > 20 and s.examples and s.possible_services for s in knowledge.signals.values()
    )
