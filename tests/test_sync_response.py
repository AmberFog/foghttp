import pytest

import foghttp
from foghttp.messages import http_status_error
from foghttp.status_codes.client_error import NOT_FOUND
from foghttp.status_codes.redirect import FOUND
from foghttp.status_codes.server_error import INTERNAL_SERVER_ERROR
from foghttp.status_codes.success import OK


def test_raise_for_status_includes_request_and_reason(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        response = client.get(f"{sync_http_server}/status/{NOT_FOUND}")

    with pytest.raises(foghttp.HTTPStatusError) as exc_info:
        response.raise_for_status()

    assert str(exc_info.value) == f"GET {sync_http_server}/status/{NOT_FOUND} returned 404 Not Found"
    assert exc_info.value.response is response


def test_raise_for_status_allows_success(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        response = client.get(f"{sync_http_server}/status/{OK}")

    response.raise_for_status()


def test_raise_for_status_handles_server_errors(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        response = client.post(f"{sync_http_server}/status/{INTERNAL_SERVER_ERROR}")

    with pytest.raises(foghttp.HTTPStatusError) as exc_info:
        response.raise_for_status()

    assert str(exc_info.value) == (
        f"POST {sync_http_server}/status/{INTERNAL_SERVER_ERROR} returned 500 Internal Server Error"
    )
    assert exc_info.value.response is response


def test_raise_for_status_uses_final_redirect_request(sync_http_server: str) -> None:
    with foghttp.Client(follow_redirects=True) as client:
        response = client.post(
            f"{sync_http_server}/redirect-to-status/{FOUND}/{NOT_FOUND}",
            json={"name": "Ada"},
        )

    with pytest.raises(foghttp.HTTPStatusError) as exc_info:
        response.raise_for_status()

    assert str(exc_info.value) == f"GET {sync_http_server}/status/{NOT_FOUND} returned 404 Not Found"
    assert response.request.method == "GET"
    assert response.request.url == f"{sync_http_server}/status/{NOT_FOUND}"
    assert response.history[0].request.method == "POST"
    assert exc_info.value.response is response


def test_response_text_uses_declared_encoding(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        response = client.get(f"{sync_http_server}/text")

    assert response.encoding == "iso-8859-1"
    assert response.text == "Latin-1: \u00e9"


def test_http_status_error_handles_unknown_status_reason() -> None:
    assert http_status_error("GET", "http://example.com", 599) == "GET http://example.com returned 599"
