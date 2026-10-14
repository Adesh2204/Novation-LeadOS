"""One storage selection point; all API writes serialize through this dependency."""

import asyncio
from functools import lru_cache

from fastapi import Request

from leados.config import Settings, settings
from leados.storage.base import StorageProvider
from leados.storage.mock import MockStorageProvider


def build_storage(config: Settings) -> StorageProvider:
    if config.leados_storage == "mock":
        return MockStorageProvider(config.mock_storage_path)
    from leados.storage.google_client import GoogleSheetsClient
    from leados.storage.google_sheets import GoogleSheetsStorageProvider

    return GoogleSheetsStorageProvider(GoogleSheetsClient(config), config)


@lru_cache(maxsize=1)
def runtime_storage():
    return build_storage(settings)


api_write_lock = asyncio.Lock()


async def get_storage(request: Request):
    from leados.services.master_view_sync import application_storage

    if request.method == "GET":
        yield runtime_storage().read_view()
        return
    async with api_write_lock:
        provider = runtime_storage()
        outcome: dict = {}
        with application_storage(provider, refresh=False, outcome=outcome):
            yield provider
        if outcome:
            request.state.master_view_outcome = outcome


get_db = get_storage  # Retains the dependency override name for existing API consumers.
