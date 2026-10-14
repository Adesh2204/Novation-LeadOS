import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import TypeVar

T = TypeVar("T")


class ProviderError(Exception):
    """Safe public error; adapters must not include credentials in messages."""

    def __init__(self, code: str, retry_after: float = 0, retryable: bool = True):
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after
        self.retryable = retryable


@dataclass(frozen=True)
class ProviderPolicy:
    timeout_seconds: float = 10
    max_attempts: int = 3
    max_concurrency: int = 4
    requests_per_minute: int = 120
    backoff_seconds: float = 0.05


class ProviderExecutor:
    def __init__(self, policy: ProviderPolicy):
        self.policy = policy
        self.semaphore = asyncio.Semaphore(policy.max_concurrency)
        self.requests: deque[float] = deque()
        self.lock = asyncio.Lock()

    async def call(self, operation: Callable[[], Awaitable[T]]) -> T:
        async with self.semaphore:
            for attempt in range(self.policy.max_attempts):
                async with self.lock:
                    timestamp = monotonic()
                    while self.requests and timestamp - self.requests[0] >= 60:
                        self.requests.popleft()
                    if len(self.requests) >= self.policy.requests_per_minute:
                        raise ProviderError("rate_limit", max(0, 60 - timestamp + self.requests[0]))
                    self.requests.append(timestamp)
                try:
                    return await asyncio.wait_for(operation(), timeout=self.policy.timeout_seconds)
                except (TimeoutError, ProviderError) as exc:
                    if isinstance(exc, ProviderError) and not exc.retryable:
                        raise
                    if attempt + 1 == self.policy.max_attempts:
                        raise ProviderError("provider_unavailable") from exc
                    retry_after = exc.retry_after if isinstance(exc, ProviderError) else 0
                    await asyncio.sleep(max(retry_after, self.policy.backoff_seconds * 2**attempt))
            raise ProviderError("provider_unavailable")
