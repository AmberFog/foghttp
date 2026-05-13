__all__ = ("CloseTrackingRawClient", "RawClientFactory", "create_test_raw_client")

import threading
import time
from typing import TYPE_CHECKING

from foghttp._client.constants import DEFAULT_MAX_REDIRECTS
from foghttp._client.raw import create_raw_client
from foghttp.limits import Limits
from foghttp.timeouts import Timeouts


if TYPE_CHECKING:
    from foghttp import _foghttp


class CloseTrackingRawClient:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class RawClientFactory:
    def __init__(self, raw_client: CloseTrackingRawClient) -> None:
        self.calls = 0
        self.delay = 0.0
        self._lock = threading.Lock()
        self.raw_client = raw_client

    def create(self, **_kwargs: object) -> CloseTrackingRawClient:
        with self._lock:
            self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        return self.raw_client


def create_test_raw_client() -> "_foghttp.RawClient":
    return create_raw_client(
        limits=Limits(),
        timeouts=Timeouts(),
        follow_redirects=False,
        max_redirects=DEFAULT_MAX_REDIRECTS,
        runtime_workers=1,
        trust_env=False,
    )
