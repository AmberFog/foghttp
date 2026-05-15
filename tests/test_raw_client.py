import pytest

from foghttp import _foghttp
from foghttp._client.raw import create_raw_client
from foghttp.limits import Limits
from foghttp.timeouts import Timeouts


RAW_CLIENT_INIT_ARGUMENTS = (
    "max_active_requests",
    "max_active_requests_per_origin",
    "max_idle_connections_per_host",
    "max_pending_requests",
    "idle_timeout",
    "keepalive",
    "connect_timeout",
    "follow_redirects",
    "max_redirects",
    "trust_env",
    "runtime_workers",
)


def test_create_raw_client_passes_transport_limits_to_rust_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_options: dict[str, object] = {}

    class RawClientProbe:
        def __init__(self, *args: object) -> None:
            captured_options.update(dict(zip(RAW_CLIENT_INIT_ARGUMENTS, args, strict=True)))

    monkeypatch.setattr(_foghttp, "RawClient", RawClientProbe)
    limits = Limits(
        max_active_requests=11,
        max_active_requests_per_origin=17,
        max_pending_requests=13,
        max_idle_connections_per_host=7,
        idle_timeout=5.5,
        keepalive=False,
    )
    timeouts = Timeouts(connect=2.5)
    follow_redirects = True
    max_redirects = 9
    runtime_workers = 3
    trust_env = False

    raw_client = create_raw_client(
        limits=limits,
        timeouts=timeouts,
        follow_redirects=follow_redirects,
        max_redirects=max_redirects,
        runtime_workers=runtime_workers,
        trust_env=trust_env,
    )

    assert isinstance(raw_client, RawClientProbe)
    assert captured_options == {
        "max_active_requests": limits.max_active_requests,
        "max_active_requests_per_origin": limits.max_active_requests_per_origin,
        "max_idle_connections_per_host": limits.max_idle_connections_per_host,
        "max_pending_requests": limits.max_pending_requests,
        "idle_timeout": limits.idle_timeout,
        "keepalive": limits.keepalive,
        "connect_timeout": timeouts.connect,
        "follow_redirects": follow_redirects,
        "max_redirects": max_redirects,
        "trust_env": trust_env,
        "runtime_workers": runtime_workers,
    }
