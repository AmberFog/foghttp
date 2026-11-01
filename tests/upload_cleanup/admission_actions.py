import pytest

from foghttp._upload_body.cleanup_owner import CleanupOwner

from .constants import COMPLETION_WATCHDOG
from .sources import SyncCloseGate


class InheritedLock:
    def __enter__(self) -> None:
        pytest.fail("an inherited cleanup lock was acquired")

    def __exit__(self, _kind: object, _error: object, _traceback: object) -> None:
        """Keep this context unreachable after the failure in __enter__."""


def complete_recovery_cleanup(owner: CleanupOwner) -> SyncCloseGate:
    source = SyncCloseGate(blocked=False)
    completion = owner.reserve(1).submit_sync(source.close)
    completion.result(timeout=COMPLETION_WATCHDOG)
    return source


async def record_async_attempt(attempts: list[str]) -> None:
    attempts.append("parent async close")
