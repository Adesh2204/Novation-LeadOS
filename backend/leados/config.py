from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", populate_by_name=True)
    leados_mode: str = "mock"
    search_provider: Literal["mock", "exa"] = "mock"
    crawler_provider: Literal["mock", "firecrawl"] = "mock"
    llm_provider: Literal["mock", "openai"] = "mock"
    embedding_provider: Literal["mock", "openai"] = "mock"
    contact_provider: Literal["mock", "contactout", "snovio", "contactout_snovio", "apollo"] = "mock"
    crm_provider: Literal["mock", "hubspot"] = "mock"
    email_provider: Literal["mock", "smtp"] = "mock"
    enable_email_send: bool = False
    leados_storage: Literal["mock", "google_sheets"] = "mock"
    mock_storage_path: str = str(ROOT / "data/leados.json")
    google_sheets_enabled: bool = False
    google_spreadsheet_id: str = ""
    google_service_account_json_path: str = ""
    google_application_credentials: str = ""
    google_service_account_json: str = ""
    storage_lock_path: str = str(ROOT / "data/storage-writer.lock")
    storage_outbox_path: str = str(ROOT / "data/sheets-outbox.json")
    sheets_timeout_seconds: float = 15
    sheets_max_attempts: int = 3
    sheets_requests_per_minute: int = 45
    sheets_max_rows: int = 10000
    show_technical_sheets: bool = False
    database_url: str = "sqlite:///./data/leados.db"
    cors_origins: str = "http://localhost:3000"
    provider_timeout_seconds: float = 10
    provider_max_attempts: int = 3
    provider_requests_per_minute: int = 1000
    exa_api_key: str = ""
    firecrawl_api_key: str = ""
    openai_api_key: str = Field(default="", repr=False)
    openai_model: str = "gpt-4.1-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    max_openai_calls_per_run: int = Field(default=40, ge=1, le=200)
    contact_out_api_key: str = Field(
        default="", repr=False, validation_alias=AliasChoices("CONTACT_OUT_API_KEY", "CONTACTOUT_API_KEY")
    )
    snovio_user_id: str = Field(default="", repr=False)
    snovio_secret: str = Field(default="", repr=False)
    hubspot_access_token: str = Field(default="", repr=False)
    n8n_encryption_key: str = Field(default="", repr=False)
    n8n_secure_cookie: bool = True
    n8n_url: str = ""
    smtp_host: str = ""
    smtp_user: str = Field(default="", repr=False)
    smtp_password: str = Field(default="", repr=False)
    live_discovery_enabled: bool = False
    live_provider_concurrency: int = Field(default=3, ge=1, le=8)
    discovery_jobs_path: str = str(ROOT / "data/discovery-jobs")
    live_provider_dry_run: bool = True
    run_live_provider_tests: bool = False
    live_research_mode: Literal["MOCK", "EXA_ONLY", "EXA_FIRECRAWL", "FULL_LIVE"] = "EXA_FIRECRAWL"

    # Credit-safe hard limits
    max_exa_searches_per_run: int = 10
    max_exa_results_per_query: int = 10
    max_exa_candidates_per_run: int = 50
    max_firecrawl_companies_per_run: int = 10
    max_firecrawl_pages_per_company: int = 4
    max_firecrawl_pages_per_run: int = 25
    max_firecrawl_depth: int = 1
    min_candidate_relevance_for_firecrawl: float = 0.70
    min_signal_confidence_for_firecrawl: float = 0.70

    # Cache TTL & daily limits
    firecrawl_cache_ttl_hours: int = 168
    exa_search_cache_ttl_hours: int = 12
    max_exa_calls_per_day: int = 50
    max_firecrawl_calls_per_day: int = 100
    exa_timeout_seconds: float = 20
    firecrawl_timeout_seconds: float = 30

    @model_validator(mode="after")
    def mock_only(self):
        if self.leados_mode not in {"mock", "live_research"}:
            raise ValueError("Supported modes are mock and live_research")
        if not self.google_service_account_json_path and self.google_application_credentials:
            self.google_service_account_json_path = self.google_application_credentials
        if self.google_service_account_json_path:
            key_path = Path(self.google_service_account_json_path)
            if not key_path.is_absolute():
                self.google_service_account_json_path = str((ROOT / key_path).resolve())
        return self


settings = Settings()
