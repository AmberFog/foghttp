__all__ = (
    "BlockingSyncHTTPServer",
    "CloseTrackingRawClient",
    "LifecycleErrorRawClient",
    "RawClientFactory",
    "create_test_raw_client",
    "wait_until_sync_client_closed",
)

from dataclasses import dataclass
import threading
import time

import foghttp
from foghttp._client.config import ClientConfig
from foghttp._client.constants import DEFAULT_MAX_REDIRECTS
from foghttp._client.options import ClientOptions
from foghttp._client.raw.lifecycle import create_raw_client
import foghttp._foghttp as _foghttp  # noqa: PLR0402
from foghttp.limits import Limits
from foghttp.timeouts import Timeouts


MAX_CLIENT_CLOSE_POLLS = 100
CLIENT_CLOSE_POLL_INTERVAL = 0.005
RAW_LIFECYCLE_ERROR = "raw lifecycle failure"


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


class LifecycleErrorRawClient(CloseTrackingRawClient):
    def stats(self) -> object:
        raise _foghttp.FogHttpLifecycleError(RAW_LIFECYCLE_ERROR)

    def transport_state(self) -> object:
        raise _foghttp.FogHttpLifecycleError(RAW_LIFECYCLE_ERROR)

    def pool_diagnostics(self) -> object:
        raise _foghttp.FogHttpLifecycleError(RAW_LIFECYCLE_ERROR)


class RawClientFactory:
    def __init__(self, raw_client: object) -> None:
        self.calls = 0
        self.delay = 0.0
        self._lock = threading.Lock()
        self.raw_client = raw_client

    def create(self, **_kwargs: object) -> object:
        with self._lock:
            self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        return self.raw_client


def create_test_raw_client() -> "_foghttp.RawClient":
    config = ClientConfig.from_options(
        ClientOptions(
            base_url=None,
            headers=None,
            params=None,
            limits=Limits(),
            timeouts=Timeouts(),
            http_versions=None,
            follow_redirects=False,
            max_redirects=DEFAULT_MAX_REDIRECTS,
            cookies=False,
            trust_env=False,
            proxy=None,
            tls=None,
            runtime="dedicated",
            runtime_workers=1,
            policy_hooks=None,
            telemetry=None,
            lifecycle_debug=None,
        ),
    )
    return create_raw_client(config=config)


def wait_until_sync_client_closed(client: foghttp.Client) -> None:
    for _attempt in range(MAX_CLIENT_CLOSE_POLLS):
        try:
            client.stats()
        except foghttp.ClientClosedError:
            return
        time.sleep(CLIENT_CLOSE_POLL_INTERVAL)

    msg = "sync client did not start rejecting requests after close started"
    raise AssertionError(msg)
