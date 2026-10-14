"""Bounded vendor requests with safe errors; never persist response bodies or credentials."""

from typing import Any

import httpx

from leados.providers.base import ProviderError


def safe_error(provider: str, status: int | None = None) -> ProviderError:
    categories = {
        400: "invalid_request",
        401: "invalid_credentials",
        402: "credits_required",
        403: "access_denied",
        404: "not_found",
        429: "rate_limited",
    }
    category = categories.get(status, "unavailable") if status is not None else "unavailable"
    return ProviderError(f"{provider}_{category}", retryable=status is None or (status >= 500))


class VendorHTTP:
    def __init__(self, name: str, base_url: str, headers: dict[str, str], transport=None):
        self.name, self.base_url, self.headers, self.transport = name, base_url, headers, transport

    async def request(self, method: str, path: str, **kwargs: Any) -> dict:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, headers=self.headers, timeout=20, transport=self.transport
            ) as client:
                response = await client.request(method, path, **kwargs)
                if not response.is_success:
                    raise safe_error(self.name, response.status_code)
                data = response.json()
                if not isinstance(data, dict):
                    raise ProviderError(f"{self.name}_invalid_response", retryable=False)
                return data
        except ProviderError:
            raise
        except (httpx.HTTPError, ValueError) as error:
            raise safe_error(self.name) from error
