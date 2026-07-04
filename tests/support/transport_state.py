__all__ = (
    "wait_for_async_transport_state",
    "wait_for_sync_transport_state",
)

import asyncio
from collections.abc import Callable
import time

import foghttp


MAX_STATE_POLLS = 100
STATE_POLL_INTERVAL = 0.01


def wait_for_sync_transport_state(
    client: foghttp.Client,
    condition: Callable[[foghttp.TransportState], bool],
    *,
    message: str,
) -> foghttp.TransportState:
    for _attempt in range(MAX_STATE_POLLS):
        state = client.dump_transport_state()
        if condition(state):
            return state
        time.sleep(STATE_POLL_INTERVAL)

    raise AssertionError(_state_message(message, client.dump_transport_state()))


async def wait_for_async_transport_state(
    client: foghttp.AsyncClient,
    condition: Callable[[foghttp.TransportState], bool],
    *,
    message: str,
) -> foghttp.TransportState:
    for _attempt in range(MAX_STATE_POLLS):
        state = client.dump_transport_state()
        if condition(state):
            return state
        await asyncio.sleep(STATE_POLL_INTERVAL)

    raise AssertionError(_state_message(message, client.dump_transport_state()))


def _state_message(message: str, state: foghttp.TransportState) -> str:
    return f"{message}: active={state['active_requests']}, pending={state['pending_requests']}, state={state}"
