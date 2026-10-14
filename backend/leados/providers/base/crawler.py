from typing import Protocol


class CrawlerProvider(Protocol):
    name: str

    async def crawl(self, document: dict) -> dict: ...
