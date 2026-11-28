import asyncio

import pytest

import foghttp
from foghttp.status_codes.success import OK

from .constants import SLOW_RESPONSE_PATH
from .gates import AsyncResponseGate
from .helpers import wait_for_async_stats


async def test_cancelling_gate_owner_releases_only_the_held_origin(
    resource_http_server: str,
    secondary_resource_http_server: str,
    resource_gate: AsyncResponseGate,
    secondary_resource_gate: AsyncResponseGate,
) -> None:
    holding_primary = asyncio.Event()

    async def hold_primary_until_cancelled() -> None:
        async with resource_gate.hold():
            holding_primary.set()
            await asyncio.Event().wait()

    async with asyncio.timeout(5.0), foghttp.AsyncClient() as client, asyncio.TaskGroup() as requests:
        secondary = requests.create_task(client.get(secondary_resource_http_server + SLOW_RESPONSE_PATH))
        async with secondary_resource_gate.hold():
            await wait_for_async_stats(client, lambda stats: stats.active_requests == 1)
            assert not resource_gate.request_started.is_set()
            primary = requests.create_task(client.get(resource_http_server + SLOW_RESPONSE_PATH))
            owner = requests.create_task(hold_primary_until_cancelled())
            await holding_primary.wait()
            assert not primary.done()

            owner.cancel("cancel the gate owner")
            with pytest.raises(asyncio.CancelledError, match="cancel the gate owner"):
                await owner
            assert (await primary).status_code == OK
            assert not secondary_resource_gate.release_response.is_set()
            assert not secondary.done()
            state = client.dump_transport_state()
            assert state["origins"][secondary_resource_http_server]["active_requests"] == 1

        assert (await secondary).status_code == OK
        assert client.stats().active_requests == 0


async def test_cancellation_as_the_blocking_request_starts() -> None:
    gate = AsyncResponseGate()
    entering = asyncio.Event()
    entered = asyncio.Event()

    async def hold_response() -> None:
        entering.set()
        async with gate.hold():
            entered.set()

    async with asyncio.timeout(5.0), asyncio.TaskGroup() as tasks:
        owner = tasks.create_task(hold_response())
        await entering.wait()
        # Wake the server wait and cancel its owner in the same event-loop turn.
        gate.request_started.set()
        owner.cancel("cancel during gate entry")
        with pytest.raises(asyncio.CancelledError, match="cancel during gate entry"):
            await owner

    assert not entered.is_set()
    assert gate.release_response.is_set()
