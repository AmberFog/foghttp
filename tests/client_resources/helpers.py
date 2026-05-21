__all__ = (
    "wait_for_async_stats",
    "wait_for_sync_stats",
)

from collections.abc import Callable

import foghttp
from tests.support.transport_stats import wait_for_async_transport_stats, wait_for_sync_transport_stats


def wait_for_sync_stats(
    client: foghttp.Client,
    condition: Callable[[foghttp.TransportStats], bool],
) -> None:
    wait_for_sync_transport_stats(client, condition, message="transport stats did not settle")


async def wait_for_async_stats(
    client: foghttp.AsyncClient,
    condition: Callable[[foghttp.TransportStats], bool],
) -> None:
    await wait_for_async_transport_stats(client, condition, message="transport stats did not settle")
