__all__ = (
    "HTTPXAsyncAdapter",
    "HTTPXSyncAdapter",
    "make_httpx_async",
    "make_httpx_sync",
)

import importlib
from typing import Any

from bench.clients.base import AsyncClientAdapter, SyncClientAdapter
from bench.clients.utils import request_kwargs, response_outcome
from bench.models import ClientConfig, ResponseOutcome, Scenario


class HTTPXAsyncAdapter(AsyncClientAdapter):
    def __init__(self, client: Any) -> None:
        self.client = client

    async def request(self, scenario: Scenario, url: str) -> ResponseOutcome:
        response = await self.client.request(
            scenario.method,
            url,
            **request_kwargs(scenario, body_key="content"),
        )
        return response_outcome(
            response=response,
            scenario=scenario,
            status_code=int(response.status_code),
            history_count=len(response.history),
            final_url=str(response.url),
        )

    async def close(self) -> None:
        await self.client.aclose()


class HTTPXSyncAdapter(SyncClientAdapter):
    def __init__(self, client: Any) -> None:
        self.client = client

    def request(self, scenario: Scenario, url: str) -> ResponseOutcome:
        response = self.client.request(
            scenario.method,
            url,
            **request_kwargs(scenario, body_key="content"),
        )
        return response_outcome(
            response=response,
            scenario=scenario,
            status_code=int(response.status_code),
            history_count=len(response.history),
            final_url=str(response.url),
        )

    def close(self) -> None:
        self.client.close()


def make_httpx_async(config: ClientConfig) -> AsyncClientAdapter:
    httpx = importlib.import_module("httpx")
    limits = httpx.Limits(
        max_connections=config.max_connections,
        max_keepalive_connections=config.max_connections,
    )
    timeout = httpx.Timeout(connect=2.0, read=10.0, write=10.0, pool=5.0)
    client = httpx.AsyncClient(
        limits=limits,
        timeout=timeout,
        trust_env=False,
        follow_redirects=config.follow_redirects,
        max_redirects=config.max_redirects,
    )
    return HTTPXAsyncAdapter(client)


def make_httpx_sync(config: ClientConfig) -> SyncClientAdapter:
    httpx = importlib.import_module("httpx")
    limits = httpx.Limits(
        max_connections=config.max_connections,
        max_keepalive_connections=config.max_connections,
    )
    timeout = httpx.Timeout(connect=2.0, read=10.0, write=10.0, pool=5.0)
    client = httpx.Client(
        limits=limits,
        timeout=timeout,
        trust_env=False,
        follow_redirects=config.follow_redirects,
        max_redirects=config.max_redirects,
    )
    return HTTPXSyncAdapter(client)
