from pathlib import Path

from faker import Faker
import pytest

from foghttp import _foghttp
from foghttp._client.constants import DEFAULT_MAX_REDIRECTS
from foghttp._client.raw import create_raw_client, send_raw_request, send_raw_request_async
from foghttp.limits import Limits
from foghttp.methods import GET
from foghttp.timeouts import Timeouts
from foghttp.tls import TLSConfig


RAW_CLIENT_INIT_ARGUMENTS = (
    "max_active_requests",
    "max_active_requests_per_origin",
    "max_idle_connections_per_host",
    "max_pending_requests",
    "max_response_body_size",
    "max_buffered_response_bytes",
    "idle_timeout",
    "keepalive",
    "connect_timeout",
    "follow_redirects",
    "max_redirects",
    "ca_certificates",
    "trust_webpki_roots",
    "trust_env",
    "runtime_workers",
)

RAW_REQUEST_ARGUMENTS = (
    "method",
    "url",
    "headers",
    "body",
    "body_replayable",
    "pool_timeout",
    "read_timeout",
    "total_timeout",
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
        max_response_body_size=19,
        max_buffered_response_bytes=23,
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
        tls=None,
    )

    assert isinstance(raw_client, RawClientProbe)
    assert captured_options == {
        "max_active_requests": limits.max_active_requests,
        "max_active_requests_per_origin": limits.max_active_requests_per_origin,
        "max_idle_connections_per_host": limits.max_idle_connections_per_host,
        "max_pending_requests": limits.max_pending_requests,
        "max_response_body_size": limits.max_response_body_size,
        "max_buffered_response_bytes": limits.max_buffered_response_bytes,
        "idle_timeout": limits.idle_timeout,
        "keepalive": limits.keepalive,
        "connect_timeout": timeouts.connect,
        "follow_redirects": follow_redirects,
        "max_redirects": max_redirects,
        "ca_certificates": (),
        "trust_webpki_roots": True,
        "trust_env": trust_env,
        "runtime_workers": runtime_workers,
    }


def test_create_raw_client_passes_tls_trust_boundary_to_rust_client(
    faker: Faker,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured_options: dict[str, object] = {}

    class RawClientProbe:
        def __init__(self, *args: object) -> None:
            captured_options.update(dict(zip(RAW_CLIENT_INIT_ARGUMENTS, args, strict=True)))

    ca_body = faker.binary(length=16)
    ca_path = tmp_path / "ca.pem"
    ca_path.write_bytes(ca_body)
    tls = TLSConfig(ca_certificates=(ca_path,), trust_webpki_roots=False)
    monkeypatch.setattr(_foghttp, "RawClient", RawClientProbe)

    raw_client = create_raw_client(
        limits=Limits(),
        timeouts=Timeouts(),
        follow_redirects=False,
        max_redirects=DEFAULT_MAX_REDIRECTS,
        runtime_workers=None,
        trust_env=False,
        tls=tls,
    )

    assert isinstance(raw_client, RawClientProbe)
    assert captured_options["ca_certificates"] == (ca_body,)
    assert captured_options["trust_webpki_roots"] is False


def test_send_raw_request_passes_request_timeouts_without_connect_timeout(faker: Faker) -> None:
    captured_options: dict[str, object] = {}
    raw_response = object()

    class RawClientProbe:
        def request(self, *args: object) -> object:
            captured_options.update(dict(zip(RAW_REQUEST_ARGUMENTS, args, strict=True)))
            return raw_response

    timeouts = Timeouts(connect=2.5, pool=3.5, read=4.5, total=5.5)
    url = faker.url()
    body = faker.binary(length=8)
    body_replayable = False

    response = send_raw_request(
        raw_client=RawClientProbe(),
        method=GET,
        url=url,
        headers=[],
        body=body,
        body_replayable=body_replayable,
        timeouts=timeouts,
    )

    assert response is raw_response
    assert captured_options == {
        "method": GET,
        "url": url,
        "headers": [],
        "body": body,
        "body_replayable": body_replayable,
        "pool_timeout": timeouts.pool,
        "read_timeout": timeouts.read,
        "total_timeout": timeouts.total,
    }


async def test_send_raw_request_async_passes_request_timeouts_without_connect_timeout(faker: Faker) -> None:
    captured_options: dict[str, object] = {}
    raw_response = object()

    class RawClientProbe:
        async def request_async(self, *args: object) -> object:
            captured_options.update(dict(zip(RAW_REQUEST_ARGUMENTS, args, strict=True)))
            return raw_response

    timeouts = Timeouts(connect=2.5, pool=3.5, read=4.5, total=5.5)
    url = faker.url()

    response = await send_raw_request_async(
        raw_client=RawClientProbe(),
        method=GET,
        url=url,
        headers=[],
        body=None,
        body_replayable=True,
        timeouts=timeouts,
    )

    assert response is raw_response
    assert captured_options == {
        "method": GET,
        "url": url,
        "headers": [],
        "body": None,
        "body_replayable": True,
        "pool_timeout": timeouts.pool,
        "read_timeout": timeouts.read,
        "total_timeout": timeouts.total,
    }
