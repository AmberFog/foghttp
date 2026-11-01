import asyncio

import pytest

import foghttp
from foghttp._upload_body.cleanup_owner import CleanupOwner
from tests.client_multipart.sources import SyncChunks
from tests.redirect_helpers import SECURITY_HEADERS_PATH

from .constants import CHAIN_OBLIGATIONS, COMPLETION_WATCHDOG
from .partial_start_actions import PartialWorkerStart
from .startup_cleanup import wait_for_async_cleanup, wait_for_cleanup
from .startup_sources import StartupCountedSource


RECOVERY_BODY = b"healthy upload after rejected physical startup"


def test_sync_client_partial_feeder_start_keeps_source_closed_and_recovers(
    monkeypatch: pytest.MonkeyPatch,
    isolated_cleanup_owner: CleanupOwner,
    sync_http_server: str,
) -> None:
    source = StartupCountedSource()
    failure = RuntimeError("sync feeder launched before startup failure")
    fault = PartialWorkerStart(
        "sync_upload",
        failure,
        isolated_cleanup_owner,
        before_rejection=source.iteration_entered,
    )
    try:
        with monkeypatch.context() as startup:
            fault.install(startup)
            with foghttp.Client() as client, pytest.raises(RuntimeError) as observed:
                client.post(sync_http_server, content=source)
        assert observed.value is failure
        assert fault.entered.is_set()
        assert source.iteration_calls == 0
        assert len(fault.completions) == CHAIN_OBLIGATIONS
        for completion in fault.completions:
            completion.result(timeout=COMPLETION_WATCHDOG)
        assert source.close_calls == 1
        assert source.iteration_calls == 0
        assert isolated_cleanup_owner.snapshot()["reserved"] == 0
    finally:
        stopped = fault.finish()

    assert stopped is True
    assert fault.finished.is_set()
    assert source.iteration_calls == 0
    assert source.next_calls == 0
    assert source.close_calls == 1
    recovery = SyncChunks((RECOVERY_BODY,))
    with foghttp.Client() as client:
        response = client.post(f"{sync_http_server}{SECURITY_HEADERS_PATH}", content=recovery)
    wait_for_cleanup(isolated_cleanup_owner)
    assert response.json()["body"] == RECOVERY_BODY.decode()
    assert recovery.close_calls == 1
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0


async def test_async_client_partial_sync_feeder_start_keeps_source_closed_and_recovers(
    monkeypatch: pytest.MonkeyPatch,
    isolated_cleanup_owner: CleanupOwner,
    sync_http_server: str,
) -> None:
    source = StartupCountedSource()
    failure = RuntimeError("async client sync feeder launched before startup failure")
    fault = PartialWorkerStart("daemon", failure, isolated_cleanup_owner)
    try:
        with monkeypatch.context() as startup:
            fault.install(startup)
            async with foghttp.AsyncClient() as client:
                with pytest.raises(RuntimeError) as observed:
                    await client.post(sync_http_server, content=source)
        assert observed.value is failure
        assert fault.entered.is_set()
        assert len(fault.completions) == CHAIN_OBLIGATIONS
        await asyncio.wait_for(
            asyncio.gather(*(asyncio.wrap_future(completion) for completion in fault.completions)),
            COMPLETION_WATCHDOG,
        )
        assert source.close_calls == 1
        assert source.iteration_calls == 0
        assert isolated_cleanup_owner.snapshot()["reserved"] == 0
    finally:
        stopped = fault.finish()

    assert stopped is True
    assert fault.finished.is_set()
    assert source.iteration_calls == 0
    assert source.next_calls == 0
    assert source.close_calls == 1
    recovery = SyncChunks((RECOVERY_BODY,))
    async with foghttp.AsyncClient() as client:
        response = await client.post(f"{sync_http_server}{SECURITY_HEADERS_PATH}", content=recovery)
    await wait_for_async_cleanup(isolated_cleanup_owner)
    assert response.json()["body"] == RECOVERY_BODY.decode()
    assert recovery.close_calls == 1
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0
