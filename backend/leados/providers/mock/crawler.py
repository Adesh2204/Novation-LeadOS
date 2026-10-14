class MockCrawlerProvider:
    name = "mock_crawler"

    async def crawl(self, document: dict) -> dict:
        return dict(document)
