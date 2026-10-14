from typing import Protocol

from leados.schemas import ResearchOutput


class LLMProvider(Protocol):
    name: str
    model: str

    async def research(self, context: dict) -> ResearchOutput: ...
