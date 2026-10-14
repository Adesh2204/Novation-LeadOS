class MockCRMProvider:
    name = "mock_crm"

    async def prepare(self, opportunity: dict) -> dict:
        return {"status": "PREVIEW_ONLY", "company_id": opportunity["company_id"], "external_write": False}
