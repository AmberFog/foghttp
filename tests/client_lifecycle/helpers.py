__all__ = (
    "BlockingSyncHTTPServer",
    "CloseTrackingRawClient",
    "RawClientFactory",
    "create_test_raw_client",
    "wait_until_sync_client_closed",
)

from dataclasses import dataclass
import threading
import time
from typing import TYPE_CHECKING

import foghttp
from foghttp._client.constants import DEFAULT_MAX_REDIRECTS
from foghttp._client.raw import create_raw_client
from foghttp.limits import Limits
from foghttp.timeouts import Timeouts


if TYPE_CHECKING:
    from foghttp import _foghttp


MAX_CLIENT_CLOSE_POLLS = 100
CLIENT_CLOSE_POLL_INTERVAL = 0.005


@dataclass(frozen=True, slots=True)
class BlockingSyncHTTPServer:
    base_url: str
    request_started: threading.Event
    release_response: threading.Event


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
        tls=None,
    )


def wait_until_sync_client_closed(client: foghttp.Client) -> None:
    for _attempt in range(MAX_CLIENT_CLOSE_POLLS):
        try:
            client.stats()
        except foghttp.ClientClosedError:
            return
        time.sleep(CLIENT_CLOSE_POLL_INTERVAL)

    msg = "sync client did not start rejecting requests after close started"
    raise AssertionError(msg)
