__all__ = (
    "AioHTTPAsyncAdapter",
    "make_aiohttp_async",
)

import importlib
import json
from typing import Any

from bench.clients.base import AsyncClientAdapter
from bench.clients.utils import json_has_keys, request_kwargs
from bench.models import ClientConfig, ResponseOutcome, Scenario


class AioHTTPAsyncAdapter(AsyncClientAdapter):
    def __init__(self, client: Any, max_redirects: int) -> None:
        self.client = client
        self.max_redirects = max_redirects

    async def request(self, scenario: Scenario, url: str) -> ResponseOutcome:
        kwargs = request_kwargs(scenario, body_key="data")
        async with self.client.request(
            scenario.method,
            url,
            allow_redirects=scenario.follow_redirects,
            max_redirects=self.max_redirects,
            **kwargs,
        ) as response:
            content = await response.read()

        json_ok = True
        if scenario.expected_json_keys:
            try:
                json_ok = json_has_keys(json.loads(content), scenario.expected_json_keys)
            except json.JSONDecodeError:
                json_ok = False

        content_length = len(content) if scenario.expected_content_length is not None else None
        return ResponseOutcome(
            status_code=int(response.status),
            json_ok=json_ok,
            content_length=content_length,
            history_count=len(response.history),
            final_url=str(response.url),
        )

    async def close(self) -> None:
        await self.client.close()


def make_aiohttp_async(config: ClientConfig) -> AsyncClientAdapter:
    aiohttp = importlib.import_module("aiohttp")
    timeout = aiohttp.ClientTimeout(total=30.0, connect=2.0, sock_read=10.0)
    connector = aiohttp.TCPConnector(
        limit=config.max_connections,
        limit_per_host=config.max_connections,
        ttl_dns_cache=300,
    )
    client = aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        trust_env=False,
    )
    return AioHTTPAsyncAdapter(client, max_redirects=config.max_redirects)
