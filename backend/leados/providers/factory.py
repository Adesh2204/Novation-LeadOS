from dataclasses import dataclass

from leados.config import settings
from leados.providers.base.contacts import ContactProvider
from leados.providers.base.crawler import CrawlerProvider
from leados.providers.base.crm import CRMProvider
from leados.providers.base.email import EmailProvider
from leados.providers.base.embeddings import EmbeddingProvider
from leados.providers.base.llm import LLMProvider
from leados.providers.base.search import SearchProvider
from leados.providers.future.apollo import ApolloContactProvider
from leados.providers.future.contacts import ContactOutContactProvider, SnovioContactProvider
from leados.providers.future.exa import ExaSearchProvider
from leados.providers.future.firecrawl import FirecrawlCrawlerProvider
from leados.providers.future.hubspot import HubSpotCRMProvider
from leados.providers.future.openai import OpenAIEmbeddingProvider, OpenAILLMProvider
from leados.providers.future.smtp import SMTPEmailProvider
from leados.providers.mock.contacts import MockContactProvider
from leados.providers.mock.crawler import MockCrawlerProvider
from leados.providers.mock.crm import MockCRMProvider
from leados.providers.mock.email import MockEmailProvider
from leados.providers.mock.embeddings import MockEmbeddingProvider
from leados.providers.mock.llm import MockLLMProvider
from leados.providers.mock.search import MockSearchProvider


@dataclass
class Providers:
    search: SearchProvider
    crawler: CrawlerProvider
    llm: LLMProvider
    embeddings: EmbeddingProvider
    contacts: ContactProvider
    crm: CRMProvider
    email: EmailProvider


def get_providers(live: bool = False) -> Providers:
    if settings.leados_mode not in {"mock", "live_research"}:
        raise ValueError("External providers have not been enabled")
    if not live:
        return Providers(
            MockSearchProvider(),
            MockCrawlerProvider(),
            MockLLMProvider(),
            MockEmbeddingProvider(),
            MockContactProvider(),
            MockCRMProvider(),
            MockEmailProvider(),
        )
    contacts = (
        SnovioContactProvider() if settings.contact_provider == "snovio" else ContactOutContactProvider()
    )
    return Providers(
        MockSearchProvider() if settings.search_provider == "mock" else ExaSearchProvider(enabled=True),
        MockCrawlerProvider()
        if settings.crawler_provider == "mock"
        else FirecrawlCrawlerProvider(enabled=True),
        MockLLMProvider() if settings.llm_provider == "mock" else OpenAILLMProvider(),
        MockEmbeddingProvider() if settings.embedding_provider == "mock" else OpenAIEmbeddingProvider(),
        MockContactProvider()
        if settings.contact_provider == "mock"
        else (ApolloContactProvider() if settings.contact_provider == "apollo" else contacts),
        MockCRMProvider() if settings.crm_provider == "mock" else HubSpotCRMProvider(),
        MockEmailProvider() if settings.email_provider == "mock" else SMTPEmailProvider(),
    )
