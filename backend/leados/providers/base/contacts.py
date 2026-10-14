from typing import Protocol


class ContactProvider(Protocol):
    name: str

    async def roles(self, company: dict, suggested_roles: list[str]) -> list[str]: ...
