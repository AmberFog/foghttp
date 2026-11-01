from typing import TYPE_CHECKING

import pytest

from foghttp._upload_body import cleanup, cleanup_owner

from .constants import CLOSE_WAIT, COMPLETION_WATCHDOG, OBLIGATION_LIMIT
from .sources import SyncCloseGate


if TYPE_CHECKING:
    from collections.abc import Iterator
    from concurrent.futures import Future

    ClientChurnCleanup = tuple[cleanup_owner.CleanupOwner, SyncCloseGate, Future[None]]


@pytest.fixture
def isolated_cleanup_owner(monkeypatch: pytest.MonkeyPatch) -> cleanup_owner.CleanupOwner:
    owner = cleanup_owner.CleanupOwner(max_active=1, max_obligations=OBLIGATION_LIMIT)
    monkeypatch.setattr(cleanup_owner._PROCESS_CLEANUP_OWNER, "owner", owner)  # noqa: SLF001
    monkeypatch.setattr(cleanup, "ASYNC_SOURCE_CLOSE_TIMEOUT", CLOSE_WAIT)
    return owner


@pytest.fixture
def client_churn_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> "Iterator[ClientChurnCleanup]":
    owner = cleanup_owner.CleanupOwner(max_active=1, max_obligations=2)
    monkeypatch.setattr(cleanup_owner._PROCESS_CLEANUP_OWNER, "owner", owner)  # noqa: SLF001
    source = SyncCloseGate()
    source_cleanup = cleanup.UploadSourceCleanup(source, reservation=owner.reserve(1))
    completion = source_cleanup.start_sync_cleanup()
    if completion is None:
        pytest.fail("cleanup did not retain an accepted callback")
    try:
        if not source.entered.wait(COMPLETION_WATCHDOG):
            pytest.fail("blocked cleanup callback did not start")
        yield owner, source, completion
    finally:
        source.release.set()
        completion.result(timeout=COMPLETION_WATCHDOG)
