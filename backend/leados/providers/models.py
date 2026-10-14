from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from leados.providers.base import ProviderError


class SearchResult(BaseModel):
    """Vendor-independent normalized search document."""

    model_config = ConfigDict(extra="ignore")

    provider: str
    query: str
    title: str
    url: str
    published_date: date | None = None
    snippet: str
    domain: str | None = None
    company_hint: str
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    provider_score: float | None = None
    possible_signal: str | None = None
    possible_vertical: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CrawledDocument(BaseModel):
    """Vendor-independent normalized crawled / scraped document."""

    model_config = ConfigDict(extra="ignore")

    url: str
    canonical_url: str
    title: str
    content: str
    published_date: date | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str
    source_type: str = "scraped_page"
    provider: str = "firecrawl"
    status: str = "SUCCESS"  # SUCCESS, CACHED, WOULD_CRAWL, NEEDS_RESEARCH, FAILED
    metadata: dict[str, Any] = Field(default_factory=dict)


class CandidatePreScreenResult(BaseModel):
    """Screening assessment performed before spending crawling credits."""

    model_config = ConfigDict(extra="ignore")

    company_name: str
    domain: str | None = None
    relevance_score: float
    qualifies: bool
    matched_signals: list[str] = Field(default_factory=list)
    matched_verticals: list[str] = Field(default_factory=list)
    rationale: str = ""


class ProviderBudget(BaseModel):
    """Run-level and per-company budget guardian preventing runaway API spend."""

    max_exa_queries: int = 10
    max_exa_results: int = 10
    max_firecrawl_companies: int = 10
    max_firecrawl_pages: int = 25
    max_pages_per_company: int = 4

    current_exa_queries: int = 0
    current_exa_results: int = 0
    current_firecrawl_companies: int = 0
    current_firecrawl_pages: int = 0
    company_pages: dict[str, int] = Field(default_factory=dict)

    def can_query_exa(self) -> bool:
        return self.current_exa_queries < self.max_exa_queries

    def can_crawl_firecrawl(self) -> bool:
        return (
            self.current_firecrawl_companies < self.max_firecrawl_companies
            and self.current_firecrawl_pages < self.max_firecrawl_pages
        )

    def can_crawl_page(self) -> bool:
        return self.current_firecrawl_pages < self.max_firecrawl_pages

    def can_crawl_company(self, company_id: str) -> bool:
        return (
            self.can_crawl_page()
            and (
                company_id in self.company_pages
                or self.current_firecrawl_companies < self.max_firecrawl_companies
            )
            and self.company_pages.get(company_id, 0) < self.max_pages_per_company
        )

    def assert_exa_available(self) -> None:
        if not self.can_query_exa():
            raise ProviderError("exa_budget_exhausted")

    def assert_firecrawl_available(self, company_id: str | None = None) -> None:
        if not self.can_crawl_firecrawl():
            raise ProviderError("firecrawl_budget_exhausted")
        if company_id and not self.can_crawl_company(company_id):
            raise ProviderError("company_crawl_budget_exhausted")

    def record_exa_query(self, result_count: int = 0) -> None:
        self.current_exa_queries += 1
        self.current_exa_results += result_count

    def record_firecrawl_page(self, company_id: str) -> None:
        if company_id not in self.company_pages:
            self.current_firecrawl_companies += 1
            self.company_pages[company_id] = 0
        self.company_pages[company_id] += 1
        self.current_firecrawl_pages += 1
