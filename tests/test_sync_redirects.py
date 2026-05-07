import pytest

import foghttp
from foghttp.status_codes.redirect import FOUND, REDIRECT_STATUS_CODES
from foghttp.status_codes.success import OK


def test_get_follows_redirects(sync_http_server: str) -> None:
    with foghttp.Client(follow_redirects=True) as client:
        for status_code in REDIRECT_STATUS_CODES:
            response = client.get(f"{sync_http_server}/redirect/{status_code}")

            assert response.status_code == OK
            assert response.url == f"{sync_http_server}/final"
            assert response.json()["request_line"] == "GET /final HTTP/1.1"
            assert len(response.history) == 1
            assert response.history[0].status_code == status_code
            assert response.history[0].url == f"{sync_http_server}/redirect/{status_code}"


def test_head_follows_redirects(sync_http_server: str) -> None:
    with foghttp.Client(follow_redirects=True) as client:
        response = client.head(f"{sync_http_server}/redirect/{FOUND}")

    assert response.status_code == OK
    assert response.url == f"{sync_http_server}/final"
    assert response.content == b""
    assert len(response.history) == 1


def test_get_redirects_respect_limit(sync_http_server: str) -> None:
    with (
        foghttp.Client(follow_redirects=True, max_redirects=1) as client,
        pytest.raises(foghttp.RequestError, match="redirect limit exceeded"),
    ):
        client.get(f"{sync_http_server}/loop")
