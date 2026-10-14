from leados.providers.base import ProviderError


class ApolloContactProvider:
    name = "apollo_disabled"
    model = "disabled"

    async def roles(self, company: dict, suggested_roles: list[str]):
        raise ProviderError("future_adapter_disabled")
