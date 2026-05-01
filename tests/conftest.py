"""Shared pytest fixtures."""

from __future__ import annotations

import httpx
import pytest

from songguesser.deezer import DeezerClient


@pytest.fixture
async def deezer_client() -> DeezerClient:
    """A DeezerClient backed by a fresh httpx.AsyncClient (replaced per-test
    by `respx` mock transports in tests that mock the network)."""
    async with httpx.AsyncClient(base_url="https://api.deezer.com") as h:
        yield DeezerClient(client=h)
