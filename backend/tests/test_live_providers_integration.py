import os

import pytest

from leados.config import settings
from leados.engine import canonical_url
from leados.providers.future.exa import ExaSearchProvider
from leados.providers.future.firecrawl import FirecrawlCrawlerProvider


def should_run_live():
    return settings.run_live_provider_tests or os.getenv("RUN_LIVE_PROVIDER_TESTS", "").lower() == "true"


@pytest.mark.skipif(
    not should_run_live(), reason="Live provider tests are opt-in only (RUN_LIVE_PROVIDER_TESTS=true)"
)
@pytest.mark.asyncio
async def test_live_exa_single_query_acceptance():
    """TINY live acceptance test: 1 query, maximum 2 results. Uses at most 1 Exa call."""
    if not settings.exa_api_key:
        pytest.skip("EXA_API_KEY not configured in .env")

    provider = ExaSearchProvider(enabled=True, num_results=2)
    # Search for a specific targeted query with max 2 results
    docs = await provider.search(company="Infosys", force_refresh=True)

    assert isinstance(docs, list)
    assert len(docs) <= 2
    if docs:
        first = docs[0]
        assert "company" in first
        assert "source_url" in first
        assert "snippet" in first
        assert first["source_url"]


@pytest.mark.skipif(
    not should_run_live(), reason="Live provider tests are opt-in only (RUN_LIVE_PROVIDER_TESTS=true)"
)
@pytest.mark.asyncio
async def test_live_firecrawl_single_page_acceptance():
    """TINY live acceptance test: 1 exact page scrape. Uses at most 1 Firecrawl credit."""
    if not settings.firecrawl_api_key:
        pytest.skip("FIRECRAWL_API_KEY not configured in .env")

    provider = FirecrawlCrawlerProvider(enabled=True, dry_run=False)
    # Scrape a known public lightweight documentation URL
    test_url = "https://example.com"
    doc = await provider.scrape_url(test_url)

    assert doc.status == "SUCCESS"
    assert canonical_url(doc.url) == canonical_url(test_url)
    assert len(doc.content) > 0
    assert len(doc.content_hash) == 64
    assert doc.provider == "firecrawl"
