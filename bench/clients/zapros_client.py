__all__ = (
    "ZaprosAsyncAdapter",
    "ZaprosSyncAdapter",
    "make_zapros_async",
    "make_zapros_sync",
)

import importlib
from typing import Any

from bench.clients.base import AsyncClientAdapter, SyncClientAdapter
from bench.clients.utils import request_kwargs, response_outcome
from bench.models import ClientConfig, ResponseOutcome, Scenario


class ZaprosAsyncAdapter(AsyncClientAdapter):
    def __init__(self, client: Any) -> None:
        self.client = client

    async def request(self, scenario: Scenario, url: str) -> ResponseOutcome:
        response = await self.client.request(
            scenario.method,
            url,
            **request_kwargs(scenario, body_key="body"),
        )
        return response_outcome(
            response=response,
            scenario=scenario,
            status_code=int(response.status),
        )

    async def close(self) -> None:
        await self.client.aclose()


class ZaprosSyncAdapter(SyncClientAdapter):
    def __init__(self, client: Any) -> None:
        self.client = client

    def request(self, scenario: Scenario, url: str) -> ResponseOutcome:
        response = self.client.request(
            scenario.method,
            url,
            **request_kwargs(scenario, body_key="body"),
        )
        return response_outcome(
            response=response,
            scenario=scenario,
            status_code=int(response.status),
        )

    def close(self) -> None:
        self.client.close()


def make_zapros_async(config: ClientConfig) -> AsyncClientAdapter:
    zapros = importlib.import_module("zapros")
    handler = zapros.AsyncStdNetworkHandler(
        total_timeout=30.0,
        connect_timeout=2.0,
        read_timeout=10.0,
        write_timeout=10.0,
        max_connections_per_host=config.max_connections,
        max_idle_connections_per_host=config.max_connections,
    )
    if config.follow_redirects:
        handler = zapros.RedirectMiddleware(handler, max_redirects=config.max_redirects)
    return ZaprosAsyncAdapter(zapros.AsyncClient(handler=handler))


def make_zapros_sync(config: ClientConfig) -> SyncClientAdapter:
    zapros = importlib.import_module("zapros")
    handler = zapros.StdNetworkHandler(
        total_timeout=30.0,
        connect_timeout=2.0,
        read_timeout=10.0,
        write_timeout=10.0,
        max_connections_per_host=config.max_connections,
        max_idle_connections_per_host=config.max_connections,
    )
    if config.follow_redirects:
        handler = zapros.RedirectMiddleware(handler, max_redirects=config.max_redirects)
    return ZaprosSyncAdapter(zapros.Client(handler=handler))
