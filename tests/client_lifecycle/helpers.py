__all__ = ("CloseTrackingRawClient", "create_test_raw_client")

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


def create_test_raw_client() -> "_foghttp.RawClient":
    return create_raw_client(
        limits=Limits(),
        timeouts=Timeouts(),
        follow_redirects=False,
        max_redirects=DEFAULT_MAX_REDIRECTS,
        runtime_workers=1,
        trust_env=False,
    )
