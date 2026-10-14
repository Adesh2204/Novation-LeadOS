from datetime import date

import pytest
from fastapi.testclient import TestClient

from leados.api import app
from leados.config import Settings
from leados.knowledge import knowledge
from leados.pipeline import Pipeline
from leados.storage.factory import get_db
from leados.storage.fake_google_client import MockGoogleSheetsClient
from leados.storage.google_sheets import GoogleSheetsStorageProvider
from leados.storage.mock import MockStorageProvider
from leados.storage.setup import initialize_workbook


@pytest.fixture(autouse=True)
def isolate_provider_caches(tmp_path, monkeypatch, request):
    # Mocked SDK calls must never pollute production usage, health or query caches.
    if request.module.__name__.endswith("test_live_providers_integration"):
        return
    from leados.config import settings

    monkeypatch.setattr(settings, "discovery_jobs_path", str(tmp_path / "jobs"))
    from leados.providers.cache import ProviderCache

    cache = ProviderCache(tmp_path / "isolated-providers.json")
    for module in (
        "leados.providers.cache",
        "leados.providers.future.exa",
        "leados.providers.future.firecrawl",
        "leados.services.live_discovery",
        "leados.api",
    ):
        monkeypatch.setattr(module + ".provider_cache", cache)


@pytest.fixture(params=["mock", "google_sheets"])
def db(tmp_path, request):
    if request.param == "mock":
        storage = MockStorageProvider(tmp_path / "test.json")
    else:
        client = MockGoogleSheetsClient()
        initialize_workbook(client)
        storage = GoogleSheetsStorageProvider(
            client,
            Settings(
                storage_outbox_path=str(tmp_path / "outbox.json"),
                storage_lock_path=str(tmp_path / "writer.lock"),
            ),
        )
    with storage.transaction(refresh=True):
        knowledge.seed(storage)
    yield storage


@pytest.fixture
async def populated(db):
    with db.transaction(refresh=True):
        run = await Pipeline(db, as_of=date(2026, 10, 6)).run()
        assert run.status == "PARTIAL"
    return db


@pytest.fixture
def client(db):
    async def override():
        with db.transaction(refresh=True):
            yield db

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()
