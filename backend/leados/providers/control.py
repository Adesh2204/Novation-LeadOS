"""Cooperative stop checked immediately before external discovery requests."""

from collections.abc import Callable
from pathlib import Path

from leados.config import settings
from leados.providers.base import ProviderError


def assert_running(should_stop: Callable[[], bool] | None = None):
    if (should_stop and should_stop()) or (
        Path(settings.discovery_jobs_path) / "STOP_LIVE_DISCOVERY"
    ).exists():
        raise ProviderError("discovery_stopped", retryable=False)
