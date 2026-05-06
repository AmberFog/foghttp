import pytest

import foghttp
from tests.conftest import OK_STATUS_CODE


async def test_get_with_params_and_json_response(http_server: str) -> None:
    async with foghttp.AsyncClient() as client:
        response = await client.get(http_server + "/users", params={"limit": 10})

    assert response.status_code == OK_STATUS_CODE
    assert response.headers["content-type"] == "application/json"
    assert response.json()["request_line"] == "GET /users?limit=10 HTTP/1.1"


async def test_post_json_body(http_server: str) -> None:
    async with foghttp.AsyncClient() as client:
        response = await client.post(http_server + "/users", json={"name": "Sergey"})

    assert response.json()["body"] == '{"name":"Sergey"}'


async def test_closed_client_rejects_requests(http_server: str) -> None:
    client = foghttp.AsyncClient()
    await client.aclose()

    with pytest.raises(foghttp.ClientClosedError):
        await client.get(http_server)


async def test_stats_track_requests(http_server: str) -> None:
    async with foghttp.AsyncClient() as client:
        await client.get(http_server)
        stats = client.stats()

    assert stats.total_requests == 1
    assert stats.failed_requests == 0


def test_sync_get_with_params_and_json_response(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        response = client.get(sync_http_server + "/users", params={"limit": 10})

    assert response.status_code == OK_STATUS_CODE
    assert response.headers["content-type"] == "application/json"
    assert response.json()["request_line"] == "GET /users?limit=10 HTTP/1.1"


def test_sync_post_json_body(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        response = client.post(sync_http_server + "/users", json={"name": "Sergey"})

    assert response.json()["body"] == '{"name":"Sergey"}'


def test_sync_closed_client_rejects_requests(sync_http_server: str) -> None:
    client = foghttp.Client()
    client.close()

    with pytest.raises(foghttp.ClientClosedError):
        client.get(sync_http_server)


def test_sync_stats_track_requests(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        client.get(sync_http_server)
        stats = client.stats()

    assert stats.total_requests == 1
    assert stats.failed_requests == 0
