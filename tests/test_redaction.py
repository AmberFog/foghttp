import pytest

import foghttp
from foghttp._redaction import REDACTED_VALUE, redact_header_value, redact_url
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
EXTENSION_KEY = "tests.private"
EXTENSION_VALUE = "redaction-extension-value"


@pytest.mark.parametrize(
    "header_name",
    [
        pytest.param("X-Amz-Security-Token", id="aws-security-token"),
        pytest.param("X-Goog-Api-Key", id="google-api-key"),
        pytest.param("X-Access-Token", id="access-token"),
        pytest.param("X-Session-Token", id="session-token"),
        pytest.param("X-Gitlab-Token", id="gitlab-token"),
        pytest.param("Private-Token", id="private-token"),
        pytest.param("Sentry-Auth", id="sentry-auth"),
        pytest.param("Vendor-Api-Key", id="vendor-api-key"),
    ],
)
def test_header_redaction_covers_common_cloud_and_vendor_secret_names(header_name: str) -> None:
    assert redact_header_value(header_name, HEADER_VALUE) == REDACTED_VALUE


@pytest.mark.parametrize(
    "header_name",
    [
        pytest.param("X-Trace-Token", id="trace-token"),
        pytest.param("X-Request-Id", id="request-id"),
    ],
)
def test_header_redaction_keeps_non_secret_operational_values(header_name: str) -> None:
    assert redact_header_value(header_name, SAFE_HEADER_VALUE) == SAFE_HEADER_VALUE


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


@pytest.mark.parametrize(
    "query_name",
    [
        pytest.param("bearer", id="bearer"),
        pytest.param("signature", id="signature"),
        pytest.param("sig", id="sig"),
        pytest.param("credential", id="credential"),
        pytest.param("X-Amz-Signature", id="aws-signature"),
        pytest.param("X-Amz-Credential", id="aws-credential"),
        pytest.param("X-Amz-Security-Token", id="aws-security-token"),
    ],
)
def test_url_redaction_covers_common_signature_and_credential_query_params(query_name: str) -> None:
    url = f"https://example.com/users?{query_name}={QUERY_VALUE}&safe={SAFE_QUERY_VALUE}"

    redacted_url = redact_url(url)

    assert QUERY_VALUE not in redacted_url
    assert f"{query_name}={REDACTED_VALUE}" in redacted_url
    assert f"safe={SAFE_QUERY_VALUE}" in redacted_url


@pytest.mark.parametrize(
    "query_name",
    [
        pytest.param("page_token", id="page-token"),
        pytest.param("trace_id", id="trace-id"),
    ],
)
def test_url_redaction_keeps_non_secret_operational_query_params(query_name: str) -> None:
    url = f"https://example.com/users?{query_name}={SAFE_QUERY_VALUE}"

    assert redact_url(url) == url


def test_request_repr_redacts_url_and_never_includes_body() -> None:
    request = foghttp.Request(
        POST,
        f"https://user:{USERINFO_VALUE}@example.com/users?token={QUERY_VALUE}",
        headers={"Authorization": f"Bearer {HEADER_VALUE}"},
        content=BODY_VALUE,
        extensions={EXTENSION_KEY: EXTENSION_VALUE},
    )

    representation = repr(request)

    assert USERINFO_VALUE not in representation
    assert QUERY_VALUE not in representation
    assert HEADER_VALUE not in representation
    assert BODY_VALUE.decode() not in representation
    assert EXTENSION_KEY not in representation
    assert EXTENSION_VALUE not in representation
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
        extensions=foghttp.RequestExtensions({EXTENSION_KEY: EXTENSION_VALUE}),
    )

    representation = repr(request_info)

    assert USERINFO_VALUE not in representation
    assert QUERY_VALUE not in representation
    assert HEADER_VALUE not in representation
    assert SAFE_HEADER_VALUE in representation
    assert EXTENSION_KEY not in representation
    assert EXTENSION_VALUE not in representation
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
            extensions=foghttp.RequestExtensions({EXTENSION_KEY: EXTENSION_VALUE}),
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
    assert EXTENSION_KEY not in representation
    assert EXTENSION_VALUE not in representation
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
