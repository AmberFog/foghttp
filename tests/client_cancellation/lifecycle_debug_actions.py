__all__ = (
    "drop_client",
    "raise_context_body_error_with_active_request",
)

import asyncio
import gc

import foghttp

from .constants import SLOW_HEADERS_PATH
from .helpers import wait_for_lifecycle_debug
from .lifecycle_debug_data import ContextBodyError
from .lifecycle_debug_predicates import has_one_buffered_request


async def raise_context_body_error_with_active_request(
    client: foghttp.AsyncClient,
    cancellation_server: str,
    tasks: list[asyncio.Task[foghttp.Response]],
) -> None:
    async with client:
        tasks.append(asyncio.create_task(client.get(cancellation_server + SLOW_HEADERS_PATH)))
        await wait_for_lifecycle_debug(
            client,
            has_one_buffered_request,
            message="active request was not tracked before context body error",
        )
        raise ContextBodyError


def drop_client(client_holder: list[foghttp.AsyncClient]) -> None:
    client_holder.clear()
    gc.collect()
