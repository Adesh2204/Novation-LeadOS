from leados.providers.base import ProviderError


class SMTPEmailProvider:
    name = "smtp_disabled"
    model = "disabled"

    async def send(self, opportunity_id: str, body: str):
        raise ProviderError("future_adapter_disabled")
