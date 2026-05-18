import pytest

import foghttp
from foghttp.messages import http_status_error
from foghttp.methods import GET, POST
from foghttp.status_codes.client_error import NOT_FOUND


HEADER_VALUE = "redaction-header-value"
COOKIE_VALUE = "session=redaction-cookie-value"
BODY_VALUE = b"redaction response body"
USERINFO_VALUE = "redaction-userinfo-value"
QUERY_VALUE = "redaction-query-value"
FRAGMENT_VALUE = "redaction-fragment-value"
SAFE_HEADER_VALUE = "trace-id"
SAFE_QUERY_VALUE = "public"


def test_headers_repr_redacts_sensitive_values() -> None:
    headers = foghttp.Headers(
        [
            ("Authorization", f"Bearer {HEADER_VALUE}"),
            ("Cookie", COOKIE_VALUE),
            ("X-Trace", SAFE_HEADER_VALUE),
        ],
    )

    representation = repr(headers)

    assert HEADER_VALUE not in representation
    assert COOKIE_VALUE not in representation
    assert "<redacted>" in representation
    assert SAFE_HEADER_VALUE in representation
    assert headers["authorization"] == f"Bearer {HEADER_VALUE}"
    assert ("Cookie", COOKIE_VALUE) in headers.multi_items()


def test_url_repr_redacts_userinfo_and_sensitive_query_and_fragment_params() -> None:
    url = foghttp.URL(
        (
            f"https://user:{USERINFO_VALUE}@example.com/users?"
            f"access_token={QUERY_VALUE}&q={SAFE_QUERY_VALUE}"
            f"#/callback?token={FRAGMENT_VALUE}&section={SAFE_QUERY_VALUE}"
        ),
    )

    representation = repr(url)

    assert USERINFO_VALUE not in representation
    assert QUERY_VALUE not in representation
    assert FRAGMENT_VALUE not in representation
    assert SAFE_QUERY_VALUE in representation
    assert "<redacted>@example.com" in representation
    assert "access_token=<redacted>" in representation
    assert "token=<redacted>" in representation
    assert USERINFO_VALUE in str(url)
    assert QUERY_VALUE in str(url)
    assert FRAGMENT_VALUE in str(url)


def test_request_repr_redacts_url_and_never_includes_body() -> None:
    request = foghttp.Request(
        POST,
        f"https://user:{USERINFO_VALUE}@example.com/users?token={QUERY_VALUE}",
        headers={"Authorization": f"Bearer {HEADER_VALUE}"},
        content=BODY_VALUE,
    )

    representation = repr(request)

    assert USERINFO_VALUE not in representation
    assert QUERY_VALUE not in representation
    assert HEADER_VALUE not in representation
    assert BODY_VALUE.decode() not in representation
    assert "<redacted>" in representation


def test_request_info_repr_redacts_url_and_headers() -> None:
    request_info = foghttp.RequestInfo(
        method=GET,
        url=f"https://user:{USERINFO_VALUE}@example.com/users?api_key={QUERY_VALUE}",
        headers=foghttp.Headers(
            [
                ("Authorization", f"Bearer {HEADER_VALUE}"),
                ("X-Trace", SAFE_HEADER_VALUE),
            ],
        ),
    )

    representation = repr(request_info)

    assert USERINFO_VALUE not in representation
    assert QUERY_VALUE not in representation
    assert HEADER_VALUE not in representation
    assert SAFE_HEADER_VALUE in representation
    assert "<redacted>" in representation


def test_response_repr_redacts_url_headers_request_and_body() -> None:
    response = foghttp.Response(
        status_code=NOT_FOUND,
        headers=foghttp.Headers([("Set-Cookie", COOKIE_VALUE)]),
        content=BODY_VALUE,
        url=f"https://user:{USERINFO_VALUE}@example.com/users?token={QUERY_VALUE}",
        request=foghttp.RequestInfo(
            method=GET,
            url=f"https://user:{USERINFO_VALUE}@example.com/users?token={QUERY_VALUE}",
            headers=foghttp.Headers([("Authorization", f"Bearer {HEADER_VALUE}")]),
        ),
        http_version="HTTP/1.1",
        elapsed=0.1,
    )

    representation = repr(response)

    assert USERINFO_VALUE not in representation
    assert QUERY_VALUE not in representation
    assert COOKIE_VALUE not in representation
    assert HEADER_VALUE not in representation
    assert BODY_VALUE.decode() not in representation
    assert f"content=<{len(BODY_VALUE)} bytes>" in representation
    assert "<redacted>" in representation


def test_http_status_error_redacts_url_secrets() -> None:
    message = http_status_error(
        GET,
        f"https://user:{USERINFO_VALUE}@example.com/users?api_key={QUERY_VALUE}",
        NOT_FOUND,
    )

    assert USERINFO_VALUE not in message
    assert QUERY_VALUE not in message
    assert message == ("GET https://<redacted>@example.com/users?api_key=<redacted> returned 404 Not Found")


def test_raise_for_status_uses_redacted_request_url() -> None:
    response = foghttp.Response(
        status_code=NOT_FOUND,
        headers=foghttp.Headers(),
        content=b"",
        url="https://example.com/users",
        request=foghttp.RequestInfo(
            method=GET,
            url=f"https://user:{USERINFO_VALUE}@example.com/users?token={QUERY_VALUE}",
            headers=foghttp.Headers(),
        ),
        http_version="HTTP/1.1",
        elapsed=0.1,
    )

    with pytest.raises(foghttp.HTTPStatusError) as exc_info:
        response.raise_for_status()

    assert USERINFO_VALUE not in str(exc_info.value)
    assert QUERY_VALUE not in str(exc_info.value)
    assert "https://<redacted>@example.com/users?token=<redacted>" in str(exc_info.value)
