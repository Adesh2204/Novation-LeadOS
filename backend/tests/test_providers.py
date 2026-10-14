import pytest
from pydantic import ValidationError

from leados.config import Settings
from leados.knowledge import knowledge
from leados.providers.base import ProviderError
from leados.providers.factory import get_providers
from leados.providers.future.exa import ExaSearchProvider
from leados.schemas import ResearchOutput


async def test_curated_rag_match_and_deterministic_embeddings():
    providers = get_providers()
    signal = knowledge.signals["AI_RECRUITMENT_SYSTEM"]
    services = await knowledge.retrieve_services(
        "ai_governance", signal.description, providers.embeddings, signal.possible_services
    )
    assert services[0] == "AI-use assessment"
    assert await providers.embeddings.embed(["same text"]) == await providers.embeddings.embed(["same text"])
    response = await providers.llm.research(
        {
            "vertical": knowledge.verticals["ai_governance"].model_dump(),
            "signal": signal.model_dump(),
            "retrieved_services": services,
            "evidence_ids": ["doc"],
        }
    )
    assert all(c.type == "INFERENCE" for c in response.inferences)
    assert "score" not in response.model_dump()


async def test_disabled_future_adapter():
    with pytest.raises(ProviderError, match="future_adapter_disabled"):
        await ExaSearchProvider().search()
    with pytest.raises(ValidationError):
        Settings(leados_mode="live")


def test_research_rejects_factual_claim_and_final_score():
    with pytest.raises(ValidationError):
        ResearchOutput(
            inferences=[{"type": "FACT", "text": "Invented fact", "evidence_ids": ["doc"]}],
            commercial_thesis="Thesis",
            why_now="Now",
            outreach_angle="Angle",
            need=1,
            mandate_value=1,
        )
    with pytest.raises(ValidationError):
        ResearchOutput(
            inferences=[],
            commercial_thesis="Thesis",
            why_now="Now",
            outreach_angle="Angle",
            need=1,
            mandate_value=1,
            score=100,
        )
