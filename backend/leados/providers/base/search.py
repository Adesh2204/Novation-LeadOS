from typing import Protocol


class SearchProvider(Protocol):
    name: str

    async def search(self, company: str | None = None) -> list[dict]: ...
