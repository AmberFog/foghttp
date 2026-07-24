from urllib.parse import urlencode, urlsplit, urlunsplit

import foghttp
from foghttp.auth import AuthRequest
from foghttp.status_codes.server_error import SERVICE_UNAVAILABLE
from foghttp.status_codes.success import OK
from tests.client_telemetry.models import RecordingTelemetrySink
from tests.redirect_helpers import header_values
from tests.support.http_routes import (
    COOKIE_EXPIRE_PATH,
    COOKIE_OPAQUE_PATH,
    COOKIE_PATH_SET_PATH,
    COOKIE_REDIRECT_PATH,
    COOKIE_RETRY_PATH,
    COOKIE_ROOT_SET_PATH,
    REPEATED_HEADERS_PATH,
    SECURITY_HEADERS_PATH,
    TEXT_PATH,
)

from .assertions import cookie_pairs, request_cookie_pairs


EXPECTED_RETRY_ATTEMPT_COUNT = 2


def test_sync_cookie_jar_is_disabled_by_default(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        client.get(sync_http_server + REPEATED_HEADERS_PATH)
        response = client.get(sync_http_server + SECURITY_HEADERS_PATH)

    assert header_values(response.json(), "cookie") == []


def test_sync_cookie_jar_stores_repeated_headers_and_redacts_values(
    sync_http_server: str,
) -> None:
    sink = RecordingTelemetrySink()
    with foghttp.Client(
        cookies=True,
        telemetry=foghttp.TelemetryConfig(sink=sink),
    ) as client:
        set_response = client.get(sync_http_server + REPEATED_HEADERS_PATH)
        response = client.get(sync_http_server + SECURITY_HEADERS_PATH)

    assert cookie_pairs(header_values(response.json(), "cookie")) == {"first=1", "second=2"}
    representation = repr((set_response, response.request, sink.events))
    assert "first=1" not in representation
    assert "second=2" not in representation
    assert "<redacted>" in representation


def test_sync_cookie_jar_preserves_opaque_values_on_the_wire(
    sync_http_server: str,
) -> None:
    with foghttp.Client(cookies=True) as client:
        client.get(sync_http_server + COOKIE_OPAQUE_PATH)
        response = client.get(sync_http_server + SECURITY_HEADERS_PATH)

    assert header_values(response.json(), "cookie") == [
        'opaque=%41%2F%25; quoted="a%2Fb"; literal=100%; encoded=%FF; empty=; equals=a=b',
    ]


def test_sync_cookie_jar_honors_path_expiry_and_explicit_cookie_precedence(
    sync_http_server: str,
) -> None:
    with foghttp.Client(cookies=True) as client:
        client.get(sync_http_server + COOKIE_ROOT_SET_PATH)
        client.get(sync_http_server + COOKIE_PATH_SET_PATH)
        matching = client.get(sync_http_server + SECURITY_HEADERS_PATH)
        outside_path = client.get(sync_http_server + TEXT_PATH)
        explicit = client.get(
            sync_http_server + SECURITY_HEADERS_PATH,
            headers={"Cookie": "caller=explicit-secret"},
        )
        client.get(sync_http_server + COOKIE_EXPIRE_PATH)
        after_expiry = client.get(sync_http_server + SECURITY_HEADERS_PATH)

    assert cookie_pairs(header_values(matching.json(), "cookie")) == {
        "root=cookie-secret",
        "scoped=cookie-secret",
    }
    assert request_cookie_pairs(outside_path) == {"root=cookie-secret"}
    assert cookie_pairs(header_values(explicit.json(), "cookie")) == {"caller=explicit-secret"}
    assert cookie_pairs(header_values(after_expiry.json(), "cookie")) == {
        "scoped=cookie-secret",
    }


def test_sync_cookie_jar_reselects_for_same_and_cross_host_redirects(
    sync_http_server: str,
) -> None:
    same_host_url = _cookie_redirect_url(sync_http_server, SECURITY_HEADERS_PATH)
    cross_host_target = _localhost_url(sync_http_server, SECURITY_HEADERS_PATH)
    cross_host_url = _cookie_redirect_url(sync_http_server, cross_host_target)

    with foghttp.Client(cookies=True, follow_redirects=True) as client:
        same_host = client.get(same_host_url)
    with foghttp.Client(cookies=True, follow_redirects=True) as client:
        cross_host = client.get(cross_host_url)

    assert cookie_pairs(header_values(same_host.json(), "cookie")) == {
        "redirect_session=cookie-secret",
    }
    assert header_values(cross_host.json(), "cookie") == []


def test_sync_cookie_jar_updates_before_retry(sync_http_server: str) -> None:
    retry = foghttp.RetryPolicy(retries=1, backoff=0, jitter=0)
    with foghttp.Client(cookies=True, retry=retry) as client:
        response = client.get(sync_http_server + COOKIE_RETRY_PATH)

    assert response.status_code == OK
    assert response.retry_trace is not None
    assert len(response.retry_trace.attempts) == EXPECTED_RETRY_ATTEMPT_COUNT
    assert response.retry_trace.attempts[0].status_code == SERVICE_UNAVAILABLE
    assert request_cookie_pairs(response) == {"retry_session=cookie-secret"}


def test_sync_auth_cookie_takes_precedence_over_managed_cookie(
    sync_http_server: str,
) -> None:
    def authenticate(_request: AuthRequest) -> dict[str, str]:
        return {"Cookie": "auth=explicit-secret"}

    with foghttp.Client(cookies=True, auth=authenticate) as client:
        client.get(sync_http_server + COOKIE_ROOT_SET_PATH)
        response = client.get(sync_http_server + SECURITY_HEADERS_PATH)

    assert cookie_pairs(header_values(response.json(), "cookie")) == {
        "auth=explicit-secret",
    }
    assert "explicit-secret" not in repr(response.request)


def test_sync_cookie_jar_updates_before_stream_is_exposed(sync_http_server: str) -> None:
    with foghttp.Client(cookies=True) as client:
        with client.stream("GET", sync_http_server + REPEATED_HEADERS_PATH) as response:
            assert response.status_code == OK
        echoed = client.get(sync_http_server + SECURITY_HEADERS_PATH)

    assert cookie_pairs(header_values(echoed.json(), "cookie")) == {"first=1", "second=2"}


def _cookie_redirect_url(base_url: str, location: str) -> str:
    return f"{base_url}{COOKIE_REDIRECT_PATH}?{urlencode({'location': location})}"


def _localhost_url(base_url: str, path: str) -> str:
    parts = urlsplit(base_url)
    return urlunsplit((parts.scheme, f"localhost:{parts.port}", path, "", ""))
