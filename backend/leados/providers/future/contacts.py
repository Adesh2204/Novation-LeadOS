import asyncio
import re
from time import monotonic

from leados.config import settings
from leados.providers.base import ProviderError
from leados.providers.http import VendorHTTP


def business_email(value: str, domain: str) -> bool:
    return (
        bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value))
        and value.rsplit("@", 1)[1].casefold() == domain.casefold()
    )


class ContactOutContactProvider:
    name = "contactout"

    def __init__(self, transport=None):
        self.http = VendorHTTP(
            self.name,
            "https://api.contactout.com",
            {"token": settings.contact_out_api_key, "authorization": "basic"},
            transport,
        )

    async def roles(self, company: dict, suggested_roles: list[str]) -> list[str]:
        # Finding named people is a separate, gated action; discovery never spends contact credits.
        return list(dict.fromkeys(suggested_roles))[:3]

    async def check(self) -> dict:
        if not settings.contact_out_api_key:
            raise ProviderError("missing_contactout_api_key", retryable=False)
        return await self.http.request("GET", "/v1/stats")

    async def enrich(self, company: dict, roles: list[str]) -> list[dict]:
        domain = company.get("domain") or ""
        if not domain:
            raise ProviderError("company_domain_required", retryable=False)
        data = await self.http.request(
            "POST",
            "/v1/people/search",
            json={
                "domain": [domain],
                "job_title": roles[:3],
                "match_experience": "current",
                "page": 1,
                "page_size": 3,
                "data_types": ["work_email"],
                "reveal_info": True,
                "detailed_experience": True,
            },
        )
        profiles = data.get("profiles") or {}
        contacts = []
        for profile in profiles.values() if isinstance(profiles, dict) else profiles:
            info = profile.get("contact_info") or {}
            current = [
                role
                for role in profile.get("experience", [])
                if isinstance(role, dict)
                and role.get("is_current")
                and (role.get("domain") or "").casefold() == domain.casefold()
            ]
            if not current:
                continue
            for email in info.get("work_emails", []):
                if business_email(email, domain):
                    contacts.append(
                        {
                            "person_name": profile.get("full_name") or profile.get("name") or "",
                            "role": current[0].get("title") or profile.get("title") or roles[0],
                            "contact_email": email,
                            "contact_source": "ContactOut",
                            "contact_status": "FOUND_UNVERIFIED",
                            "confidence": 0.7,
                        }
                    )
                    break
        return contacts[:3]


class SnovioContactProvider:
    name = "snovio"

    def __init__(self, transport=None):
        self.http = VendorHTTP(self.name, "https://api.snov.io", {}, transport)
        self.token = ""
        self.expires_at = 0.0

    async def roles(self, company: dict, suggested_roles: list[str]) -> list[str]:
        return list(dict.fromkeys(suggested_roles))[:3]

    async def authorize(self):
        if self.token and monotonic() < self.expires_at:
            return
        if not settings.snovio_user_id or not settings.snovio_secret:
            raise ProviderError("missing_snovio_credentials", retryable=False)
        data = await self.http.request(
            "POST",
            "/v1/oauth/access_token",
            data={
                "grant_type": "client_credentials",
                "client_id": settings.snovio_user_id,
                "client_secret": settings.snovio_secret,
            },
        )
        token = data.get("access_token")
        if not token:
            raise ProviderError("snovio_invalid_credentials", retryable=False)
        self.token = token
        self.expires_at = monotonic() + max(0, int(data.get("expires_in", 3600)) - 60)
        self.http.headers = {"Authorization": f"Bearer {token}"}

    async def check(self) -> dict:
        await self.authorize()
        data = await self.http.request("GET", "/v1/get-balance")
        if data.get("success") is False:
            raise ProviderError("snovio_access_denied", retryable=False)
        return data

    async def verify(self, emails: list[str]) -> dict[str, str]:
        if not emails:
            return {}
        await self.authorize()
        start = await self.http.request("POST", "/v2/email-verification/start", data={"emails[]": emails[:3]})
        task = (start.get("data") or {}).get("task_hash", "")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,150}", task):
            raise ProviderError("snovio_invalid_task", retryable=False)
        for attempt in range(4):
            result = await self.http.request(
                "GET", "/v2/email-verification/result", params={"task_hash": task}
            )
            if result.get("status") == "completed":
                return {
                    item["email"]: (
                        "VALIDATED"
                        if item.get("result", {}).get("smtp_status") == "valid"
                        and not any(
                            item.get("result", {}).get(key)
                            for key in ["is_webmail", "is_disposable", "is_gibberish"]
                        )
                        and item.get("result", {}).get("is_valid_format")
                        else "UNVERIFIED"
                    )
                    for item in result.get("data", [])
                    if item.get("email") in emails
                }
            if attempt < 3:
                await asyncio.sleep(1)
        # Pending/unknown/catch-all addresses never become validated.
        return {email: "VERIFICATION_PENDING" for email in emails}
