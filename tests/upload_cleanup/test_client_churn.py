from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

import foghttp
from foghttp.errors import LifecycleError
from tests.client_multipart.sources import SyncChunks
from tests.redirect_helpers import SECURITY_HEADERS_PATH

from .constants import COMPLETION_WATCHDOG


if TYPE_CHECKING:
    from concurrent.futures import Future

    from foghttp._upload_body.cleanup_owner import CleanupOwner

    from .sources import SyncCloseGate


CLIENT_CHURN_COUNT = 3
RECOVERY_BODY = b"cleanup capacity recovered"


def test_new_sync_clients_cannot_reset_blocked_process_cleanup_capacity(
    client_churn_cleanup: tuple[CleanupOwner, SyncCloseGate, Future[None]],
    sync_http_server: str,
) -> None:
    owner, callback, completion = client_churn_cleanup
    for _index in range(CLIENT_CHURN_COUNT):
        source = SyncChunks((b"refused",))
        with (
            foghttp.Client() as client,
            pytest.raises(LifecycleError, match="upload cleanup capacity exhausted"),
        ):
            client.post(sync_http_server, content=source)
        assert source.close_calls == 0
        assert owner.snapshot()["reserved"] == 1
        assert owner.snapshot()["active"] == 1
        assert callback.calls == 1

    callback.release.set()
    completion.result(timeout=COMPLETION_WATCHDOG)
    assert owner.snapshot()["reserved"] == 0
    source = SyncChunks((RECOVERY_BODY,))
    with foghttp.Client() as client:
        response = client.post(f"{sync_http_server}{SECURITY_HEADERS_PATH}", content=source)
    assert response.json()["body"] == RECOVERY_BODY.decode()
    assert source.close_calls == 1
    assert owner.snapshot()["reserved"] == 0


async def test_new_async_clients_cannot_reset_blocked_process_cleanup_capacity(
    client_churn_cleanup: tuple[CleanupOwner, SyncCloseGate, Future[None]],
    sync_http_server: str,
) -> None:
    owner, callback, completion = client_churn_cleanup
    for _index in range(CLIENT_CHURN_COUNT):
        source = SyncChunks((b"refused",))
        async with foghttp.AsyncClient() as client:
            with pytest.raises(LifecycleError, match="upload cleanup capacity exhausted"):
                await client.post(sync_http_server, content=source)
        assert source.close_calls == 0
        assert owner.snapshot()["reserved"] == 1
        assert owner.snapshot()["active"] == 1
        assert callback.calls == 1

    callback.release.set()
    await asyncio.wait_for(asyncio.wrap_future(completion), COMPLETION_WATCHDOG)
    assert owner.snapshot()["reserved"] == 0
    source = SyncChunks((RECOVERY_BODY,))
    async with foghttp.AsyncClient() as client:
        response = await client.post(f"{sync_http_server}{SECURITY_HEADERS_PATH}", content=source)
    assert response.json()["body"] == RECOVERY_BODY.decode()
    assert source.close_calls == 1
    assert owner.snapshot()["reserved"] == 0
