from leados.config import settings
from leados.providers.base import ProviderError
from leados.providers.http import VendorHTTP


class HubSpotCRMProvider:
    name = "hubspot"
    model = "crm_v3"

    def __init__(self, transport=None):
        self.http = VendorHTTP(
            self.name,
            "https://api.hubapi.com",
            {"Authorization": f"Bearer {settings.hubspot_access_token}"},
            transport,
        )

    async def check(self) -> dict:
        if not settings.hubspot_access_token:
            raise ProviderError("missing_hubspot_access_token", retryable=False)
        return await self.http.request(
            "GET", "/crm/v3/objects/companies", params={"limit": 1, "properties": "name"}
        )

    async def prepare(self, opportunity: dict):
        return {"status": "PREVIEW_ONLY", "external_write": False, "properties": self.properties(opportunity)}

    def properties(self, opportunity: dict) -> dict:
        return {
            "name": opportunity["company"],
            "domain": opportunity["domain"],
            "description": f"LeadOS opportunity {opportunity['id']}\nService: {opportunity['service']}\nScore: {opportunity['score']}/100\nStatus: {opportunity['status']}\n{opportunity['thesis']}",
        }

    async def sync(self, opportunity: dict) -> dict:
        if not settings.hubspot_access_token:
            raise ProviderError("missing_hubspot_access_token", retryable=False)
        properties = self.properties(opportunity)
        existing = await self.http.request(
            "POST",
            "/crm/v3/objects/companies/search",
            json={
                "filterGroups": [
                    {"filters": [{"propertyName": "domain", "operator": "EQ", "value": properties["domain"]}]}
                ],
                "properties": ["name", "domain"],
                "limit": 2,
            },
        )
        matches = existing.get("results", [])
        if len(matches) > 1:
            raise ProviderError("hubspot_ambiguous_company", retryable=False)
        if matches:
            # Keep an existing company's user-owned name/description; add no duplicate company.
            company_id = matches[0]["id"]
            return {"status": "LINKED", "company_id": company_id, "external_write": False}
        created = await self.http.request(
            "POST", "/crm/v3/objects/companies", json={"properties": properties}
        )
        return {"status": "CREATED", "company_id": created["id"], "external_write": True}
