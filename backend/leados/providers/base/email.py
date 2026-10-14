from typing import Protocol


class EmailProvider(Protocol):
    name: str

    async def send(self, opportunity_id: str, body: str) -> dict: ...
