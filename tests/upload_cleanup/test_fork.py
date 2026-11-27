from contextlib import ExitStack
import os
from typing import TYPE_CHECKING

import pytest

from foghttp._upload_body import cleanup, cleanup_owner
from foghttp._upload_body.cleanup_start import (
    collect_worker_interrupts,
    defer_worker_interrupts,
    report_worker_interrupt,
)
from tests.client_lifecycle.fork_actions import run_in_fork

from .cleanup_actions import finish_sync_cleanups
from .constants import COMPLETION_WATCHDOG, OBLIGATION_LIMIT
from .sources import SyncCloseGate


if TYPE_CHECKING:
    from concurrent.futures import Future


pytestmark = pytest.mark.skipif(not hasattr(os, "fork"), reason="os.fork is unavailable")


def test_fork_child_resets_capacity_and_never_closes_parent_providers(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    sources = [SyncCloseGate() for _index in range(OBLIGATION_LIMIT)]
    cleanups = [
        cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(1)) for source in sources
    ]
    completions: list[Future[None]] = []
    try:
        for source_cleanup in cleanups:
            completion = source_cleanup.start_sync_cleanup()
            assert completion is not None
            completions.append(completion)
        assert sources[0].entered.wait(COMPLETION_WATCHDOG)

        def child_cleanup() -> None:
            child_owner = cleanup_owner.get_cleanup_owner()
            assert child_owner is not isolated_cleanup_owner
            assert cleanup_owner.cleanup_snapshot()["pid"] == os.getpid()
            assert cleanup_owner.cleanup_snapshot()["reserved"] == 0
            for source_cleanup in cleanups:
                source_cleanup.close()
            assert [source.calls for source in sources] == [1, 0, 0, 0]
            child_source = SyncCloseGate(blocked=False)
            child_cleanup = cleanup.UploadSourceCleanup(child_source)
            completion = child_cleanup.start_sync_cleanup()
            assert completion is not None
            completion.result(timeout=COMPLETION_WATCHDOG)
            assert child_source.calls == 1
            assert cleanup_owner.cleanup_snapshot()["reserved"] == 0

        result = run_in_fork(child_cleanup)

        assert result.ok is True, result.message
        assert result.exit_status == 0
        assert cleanup_owner.cleanup_snapshot()["reserved"] == OBLIGATION_LIMIT
        assert sources[0].finished.is_set() is False
    finally:
        finish_sync_cleanups(sources, completions)

    assert all(source.calls == 1 for source in sources)
    assert cleanup_owner.cleanup_snapshot()["reserved"] == 0


def test_fork_inside_cleanup_registration_keeps_interruptions_in_their_own_process() -> None:
    parent_interrupt = KeyboardInterrupt()
    part_interrupt = GeneratorExit()
    with ExitStack() as registration:
        registration.enter_context(defer_worker_interrupts())
        report_worker_interrupt(parent_interrupt)
        with ExitStack() as parts:
            part_errors = parts.enter_context(collect_worker_interrupts())
            report_worker_interrupt(part_interrupt)

            def child_cleanup() -> None:
                parts.close()
                assert not part_errors
                child_interrupt = GeneratorExit()
                with pytest.raises(GeneratorExit) as interrupted:
                    report_worker_interrupt(child_interrupt)
                assert interrupted.value is child_interrupt
                registration.close()

            result = run_in_fork(child_cleanup)
            assert result.ok is True, result.message
            assert result.exit_status == 0
        assert part_errors == [part_interrupt]
        with pytest.raises(KeyboardInterrupt) as caught:
            registration.close()
    assert caught.value is parent_interrupt
