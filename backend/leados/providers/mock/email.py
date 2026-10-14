from leados.providers.base import ProviderError


class MockEmailProvider:
    name = "mock_email"

    async def send(self, opportunity_id: str, body: str) -> dict:
        # No transport exists in V1, even if a caller misconfigures the environment.
        raise ProviderError("email_transport_disabled_in_v1")
