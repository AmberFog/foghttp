from functools import partial
from unittest.mock import Mock

import pytest

from foghttp._upload_body import cleanup, cleanup_owner
from foghttp._upload_body.thread_bridge import start_daemon_worker
from foghttp.errors import LifecycleError

from .constants import COMPLETION_WATCHDOG
from .iterator_sources import SyncIteratorFactory


def test_close_during_owned_iterator_creation_retains_spare_until_late_iterator_closes(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    source = SyncIteratorFactory()
    owner = cleanup.UploadSourceCleanup(source)
    created = start_daemon_worker(partial(owner.create_iterator, partial(iter, source)))
    refused_factory = Mock()
    try:
        assert source.entered.wait(COMPLETION_WATCHDOG)
        owner.close()
        owner.completion.result(timeout=COMPLETION_WATCHDOG)
        assert source.close_calls == 1
        assert isolated_cleanup_owner.snapshot()["reserved"] == 1

        with pytest.raises(LifecycleError, match="already closing"):
            owner.create_iterator(refused_factory)

        refused_factory.assert_not_called()
        assert isolated_cleanup_owner.snapshot()["reserved"] == 1
        source.release.set()
        assert created.result(timeout=COMPLETION_WATCHDOG) is source.iterator
        assert source.iterator.entered.wait(COMPLETION_WATCHDOG)
        assert source.iterator.finished.is_set() is False
        assert source.iterator.calls == 1
        assert isolated_cleanup_owner.snapshot()["reserved"] == 1
        assert isolated_cleanup_owner.snapshot()["active"] == 1
    finally:
        source.release.set()
        source.iterator.release.set()
        created.result(timeout=COMPLETION_WATCHDOG)
        iterator_cleanup = owner.iteration.track(source.iterator)
        completion = iterator_cleanup.start_sync_cleanup()
        assert completion is not None
        completion.result(timeout=COMPLETION_WATCHDOG)
        owner.close()

    assert source.close_calls == 1
    assert source.iterator.calls == 1
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0
