class MockContactProvider:
    name = "mock_contacts"

    async def roles(self, company: dict, suggested_roles: list[str]) -> list[str]:
        return list(dict.fromkeys(suggested_roles))[:4]
