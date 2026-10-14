import json

from leados.config import ROOT


class MockSearchProvider:
    name = "mock_search"

    async def search(self, company: str | None = None) -> list[dict]:
        docs = json.loads((ROOT / "fixtures/market.json").read_text())["documents"]
        if company:
            docs = [
                d
                for d in docs
                if company.casefold() in d["company"]["name"].casefold()
                or company.casefold() == (d["company"]["domain"] or "").casefold()
            ]
        return docs
