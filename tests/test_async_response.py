from faker import Faker
import pytest

import foghttp
from foghttp.methods import GET, POST
from foghttp.status_codes.client_error import NOT_FOUND
from foghttp.status_codes.redirect import FOUND
from foghttp.status_codes.server_error import INTERNAL_SERVER_ERROR


async def test_raise_for_status_includes_request_and_reason(http_server: str) -> None:
    async with foghttp.AsyncClient() as client:
        response = await client.get(f"{http_server}/status/{NOT_FOUND}")

    with pytest.raises(foghttp.HTTPStatusError) as exc_info:
        response.raise_for_status()

    assert str(exc_info.value) == f"GET {http_server}/status/{NOT_FOUND} returned 404 Not Found"
    assert exc_info.value.response is response


async def test_raise_for_status_handles_server_errors(http_server: str) -> None:
    async with foghttp.AsyncClient() as client:
        response = await client.post(f"{http_server}/status/{INTERNAL_SERVER_ERROR}")

    with pytest.raises(foghttp.HTTPStatusError) as exc_info:
        response.raise_for_status()

    assert str(exc_info.value) == (
        f"POST {http_server}/status/{INTERNAL_SERVER_ERROR} returned 500 Internal Server Error"
    )
    assert exc_info.value.response is response


async def test_raise_for_status_uses_final_redirect_request(http_server: str, faker: Faker) -> None:
    async with foghttp.AsyncClient(follow_redirects=True) as client:
        response = await client.post(
            f"{http_server}/redirect-to-status/{FOUND}/{NOT_FOUND}",
            json={"name": faker.name()},
        )

    with pytest.raises(foghttp.HTTPStatusError) as exc_info:
        response.raise_for_status()

    assert str(exc_info.value) == f"GET {http_server}/status/{NOT_FOUND} returned 404 Not Found"
    assert response.request.method == GET
    assert response.request.url == f"{http_server}/status/{NOT_FOUND}"
    assert response.history[0].request.method == POST
    assert exc_info.value.response is response


async def test_response_text_uses_declared_encoding(http_server: str) -> None:
    async with foghttp.AsyncClient() as client:
        response = await client.get(f"{http_server}/text")

    assert response.encoding == "iso-8859-1"
    assert response.text == "Latin-1: \u00e9"
