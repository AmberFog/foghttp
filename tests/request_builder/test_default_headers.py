from faker import Faker
import pytest

import foghttp
from foghttp.methods import GET


DEFAULT_ACCEPT = "application/json"
REQUEST_ACCEPT = "text/plain"
DEFAULT_TENANT = "tenant-default"
DEFAULT_TRACE = "trace-default"
REQUEST_TRACE = "trace-request"
ECHO_HEADERS_PATH = "/headers/echo"


def test_sync_build_request_applies_default_headers() -> None:
    with foghttp.Client(headers={"Accept": DEFAULT_ACCEPT}) as client:
        request = client.build_request(GET, "https://api.example.com/users")

    assert request.headers["accept"] == DEFAULT_ACCEPT


async def test_async_build_request_applies_default_headers() -> None:
    async with foghttp.AsyncClient(headers={"Accept": DEFAULT_ACCEPT}) as client:
        request = client.build_request(GET, "https://api.example.com/users")

    assert request.headers["accept"] == DEFAULT_ACCEPT


def test_request_headers_override_default_headers_case_insensitively() -> None:
    default_headers = [
        ("Accept", DEFAULT_ACCEPT),
        ("X-Tenant", DEFAULT_TENANT),
        ("X-Trace", DEFAULT_TRACE),
    ]
    request_headers = [
        ("accept", REQUEST_ACCEPT),
        ("x-trace", REQUEST_TRACE),
        ("X-Trace", f"{REQUEST_TRACE}-second"),
    ]

    with foghttp.Client(headers=default_headers) as client:
        request = client.build_request(
            GET,
            "https://api.example.com/users",
            headers=request_headers,
        )

    assert request.headers.multi_items() == [
        ("X-Tenant", DEFAULT_TENANT),
        ("accept", REQUEST_ACCEPT),
        ("x-trace", REQUEST_TRACE),
        ("X-Trace", f"{REQUEST_TRACE}-second"),
    ]


def test_default_headers_snapshot_user_supplied_headers(faker: Faker) -> None:
    default_headers = foghttp.Headers([("Accept", DEFAULT_ACCEPT), ("X-Trace", faker.slug())])
    expected_trace_values = default_headers.get_list("x-trace")

    with foghttp.Client(headers=default_headers) as client:
        default_headers["Accept"] = REQUEST_ACCEPT
        default_headers.add("X-Trace", faker.slug())
        request = client.build_request(GET, "https://api.example.com/users")

    assert request.headers["accept"] == DEFAULT_ACCEPT
    assert request.headers.get_list("x-trace") == expected_trace_values


def test_default_headers_reject_transport_managed_header() -> None:
    with pytest.raises(ValueError, match="managed by FogHTTP transport"):
        foghttp.Client(headers={"Host": "api.example.com"})


async def test_async_default_headers_reject_transport_managed_header() -> None:
    with pytest.raises(ValueError, match="managed by FogHTTP transport"):
        foghttp.AsyncClient(headers={"Content-Length": "10"})


def test_sync_request_sends_default_headers(sync_http_server: str) -> None:
    headers = foghttp.Headers(
        [
            ("X-Repeat", DEFAULT_TRACE),
            ("x-repeat", REQUEST_TRACE),
            ("X-Tenant", DEFAULT_TENANT),
        ],
    )

    with foghttp.Client(headers=headers) as client:
        response = client.get(f"{sync_http_server}{ECHO_HEADERS_PATH}")

    assert response.json()["x-repeat"] == [DEFAULT_TRACE, REQUEST_TRACE]
    assert response.request.headers.get_list("x-repeat") == [DEFAULT_TRACE, REQUEST_TRACE]
    assert response.request.headers["x-tenant"] == DEFAULT_TENANT


async def test_async_request_sends_default_headers(http_server: str) -> None:
    headers = foghttp.Headers(
        [
            ("X-Repeat", DEFAULT_TRACE),
            ("x-repeat", REQUEST_TRACE),
            ("X-Tenant", DEFAULT_TENANT),
        ],
    )

    async with foghttp.AsyncClient(headers=headers) as client:
        response = await client.get(f"{http_server}{ECHO_HEADERS_PATH}")

    assert response.json()["x-repeat"] == [DEFAULT_TRACE, REQUEST_TRACE]
    assert response.request.headers.get_list("x-repeat") == [DEFAULT_TRACE, REQUEST_TRACE]
    assert response.request.headers["x-tenant"] == DEFAULT_TENANT
