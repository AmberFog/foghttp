__all__ = (
    "FogHTTPAsyncAdapter",
    "FogHTTPSyncAdapter",
    "make_foghttp_async",
    "make_foghttp_sync",
)

import importlib
from typing import Any

from bench.clients.base import AsyncClientAdapter, SyncClientAdapter
from bench.clients.utils import request_kwargs, response_outcome, stats_from_client
from bench.models import ClientConfig, ResponseOutcome, Scenario


class FogHTTPAsyncAdapter(AsyncClientAdapter):
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
            final_url=response.url,
        )

    async def close(self) -> None:
        await self.client.aclose()

    def stats(self) -> dict[str, Any] | None:
        return stats_from_client(self.client)


class FogHTTPSyncAdapter(SyncClientAdapter):
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
            final_url=response.url,
        )

    def close(self) -> None:
        self.client.close()

    def stats(self) -> dict[str, Any] | None:
        return stats_from_client(self.client)


def make_foghttp_async(config: ClientConfig) -> AsyncClientAdapter:
    foghttp = importlib.import_module("foghttp")
    limits = foghttp_limits(foghttp, config)
    timeouts = foghttp.Timeouts(connect=2.0, read=10.0, write=10.0, pool=5.0, total=30.0)
    client = foghttp.AsyncClient(
        limits=limits,
        timeouts=timeouts,
        follow_redirects=config.follow_redirects,
        max_redirects=config.max_redirects,
    )
    return FogHTTPAsyncAdapter(client)


def make_foghttp_sync(config: ClientConfig) -> SyncClientAdapter:
    foghttp = importlib.import_module("foghttp")
    limits = foghttp_limits(foghttp, config)
    timeouts = foghttp.Timeouts(connect=2.0, read=10.0, write=10.0, pool=5.0, total=30.0)
    client = foghttp.Client(
        limits=limits,
        timeouts=timeouts,
        follow_redirects=config.follow_redirects,
        max_redirects=config.max_redirects,
    )
    return FogHTTPSyncAdapter(client)


def foghttp_limits(foghttp: Any, config: ClientConfig) -> Any:
    return foghttp.Limits(
        max_connections=config.max_connections,
        max_connections_per_host=config.max_connections,
        max_pending_acquires=max(config.max_connections * 10, config.concurrency),
    )
