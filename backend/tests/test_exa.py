from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from leados.api import app
from leados.providers.base import ProviderError
from leados.providers.future.exa import ExaSearchProvider
from leados.schemas import MarketDocument


def test_exa_provider_disabled_by_default():
    provider = ExaSearchProvider(enabled=False)
    with pytest.raises(ProviderError, match="future_adapter_disabled"):
        provider._get_client()


def test_exa_provider_missing_api_key():
    provider = ExaSearchProvider(api_key="", enabled=True)
    with pytest.raises(ProviderError, match="missing_exa_api_key"):
        provider._get_client()


def test_exa_format_results_to_documents():
    provider = ExaSearchProvider(api_key="test-key", enabled=True)

    mock_res = MagicMock()
    mock_res.results = [
        MagicMock(
            url="https://example.com/press/leadership",
            title="Acme Corp appoints John Doe as CEO",
            published_date="2026-10-07T00:00:00.000Z",
            author="Editorial Team",
            highlights=["Acme Corp has appointed John Doe as Chief Executive Officer."],
        )
    ]
    mock_res.output = MagicMock()
    mock_res.output.content = {
        "events": [
            {
                "company_name": "Acme Corp",
                "source_url": "https://example.com/press/leadership",
                "sector": "Enterprise Software",
                "country": "India",
                "person_hired": "John Doe",
                "role_title": "CEO",
                "event_summary": "Acme Corp appointed John Doe as CEO to lead expansion in India.",
            }
        ]
    }

    docs = provider._format_results_to_documents(mock_res)
    assert len(docs) == 1
    doc = docs[0]
    assert doc["company"]["name"] == "Acme Corp"
    assert doc["company"]["sector"] == "Enterprise Software"
    assert doc["company"]["country"] == "India"
    assert "John Doe" in doc["snippet"]
    assert "Chief Executive Officer" in doc["snippet"]
    assert doc["snippet"] == mock_res.results[0].highlights[0]
    assert str(doc["source_url"]) == "https://example.com/press/leadership"
    # Verify MarketDocument model validation succeeds
    validated = MarketDocument.model_validate(doc)
    assert validated.company.name == "Acme Corp"


def test_exa_format_fallback_when_no_structured_output():
    provider = ExaSearchProvider(api_key="test-key", enabled=True)

    mock_res = MagicMock()
    mock_res.results = [
        MagicMock(
            url="https://example.com/news/1",
            title="FinTech Corp appoints Jane Smith as Chief Compliance Officer",
            published_date="2026-10-06T12:00:00.000Z",
            author="Staff Reporter",
            highlights=["FinTech Corp appoints Jane Smith as CCO."],
        )
    ]
    mock_res.output = None

    docs = provider._format_results_to_documents(mock_res)
    assert len(docs) == 1
    doc = docs[0]
    assert "FinTech Corp" in doc["company"]["name"]
    assert doc["company"]["country"] == "Unknown"
    validated = MarketDocument.model_validate(doc)
    assert str(validated.source_url) == "https://example.com/news/1"


@pytest.mark.asyncio
async def test_exa_search_with_mocked_client():
    provider = ExaSearchProvider(api_key="test-key", enabled=True)

    mock_client = MagicMock()
    mock_res = MagicMock()
    mock_res.results = [
        MagicMock(
            url="https://apexcloud.com/news/hiring",
            title="Apex Cloud names Rahul Verma as VP Engineering",
            highlights=["Apex Cloud names Rahul Verma as VP Engineering."],
            published_date="2026-10-07",
            author=None,
        )
    ]
    mock_res.output = MagicMock()
    mock_res.output.content = {
        "events": [
            {
                "company_name": "Apex Cloud",
                "sector": "Cloud Infrastructure",
                "country": "India",
                "person_hired": "Rahul Verma",
                "role_title": "VP Engineering",
                "event_summary": "Apex Cloud names Rahul Verma as VP Engineering.",
            }
        ]
    }
    mock_client.search.return_value = mock_res
    provider._client = mock_client

    docs = await provider.search(company="Apex Cloud", force_refresh=True)
    assert len(docs) == 1
    assert docs[0]["company"]["name"] == "Apex Cloud"
    mock_client.search.assert_called_once()
    call_kwargs = mock_client.search.call_args[1]
    # Verify adhering to build-with-exa
    assert call_kwargs["type"] == "auto"
    assert call_kwargs["contents"] == {"highlights": True}
    assert "Apex Cloud" in call_kwargs["query"]
    assert "output_schema" in call_kwargs


def test_exa_api_status_endpoint():
    client = TestClient(app)
    resp = client.get("/discovery/exa/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "exa"
    assert "configured" in data
    assert data["recommended_request"]["type"] == "auto"
    assert data["recommended_request"]["contents"] == {"highlights": True}
