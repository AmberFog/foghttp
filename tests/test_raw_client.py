import pytest

from foghttp import _foghttp
from foghttp._client.raw import create_raw_client
from foghttp.limits import Limits
from foghttp.timeouts import Timeouts


def test_create_raw_client_passes_transport_limits_to_rust_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_args: dict[str, tuple[object, ...]] = {}

    class RawClientProbe:
        def __init__(self, *args: object) -> None:
            captured_args["args"] = args

    monkeypatch.setattr(_foghttp, "RawClient", RawClientProbe)

    raw_client = create_raw_client(
        limits=Limits(
            max_active_requests=11,
            max_pending_requests=13,
            max_idle_connections_per_host=7,
            idle_timeout=5.5,
            keepalive=False,
        ),
        timeouts=Timeouts(connect=2.5),
        follow_redirects=True,
        max_redirects=9,
        runtime_workers=3,
        trust_env=False,
    )

    assert isinstance(raw_client, RawClientProbe)
    assert captured_args["args"] == (
        11,
        7,
        13,
        5.5,
        False,
        2.5,
        True,
        9,
        False,
        3,
    )
