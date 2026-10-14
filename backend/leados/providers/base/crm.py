from typing import Protocol


class CRMProvider(Protocol):
    name: str

    async def prepare(self, opportunity: dict) -> dict: ...
