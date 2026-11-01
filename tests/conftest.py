__all__ = ("pytest_plugins",)

import pytest

from foghttp._upload_body import cleanup_owner


pytest_plugins = (
    "tests.support.async_http_server",
    "tests.support.sync_http_server",
)


@pytest.fixture
def cold_cleanup_owner(monkeypatch: pytest.MonkeyPatch) -> cleanup_owner.CleanupOwner:
    owner = cleanup_owner.CleanupOwner()
    monkeypatch.setattr(cleanup_owner._PROCESS_CLEANUP_OWNER, "owner", owner)  # noqa: SLF001
    return owner
