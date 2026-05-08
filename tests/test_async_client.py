from faker import Faker
import orjson
import pytest

import foghttp
from foghttp.status_codes.success import OK


async def test_get_with_params_and_json_response(http_server: str) -> None:
    async with foghttp.AsyncClient() as client:
        response = await client.get(http_server + "/users", params={"limit": 10})

    assert response.status_code == OK
    assert response.request.method == "GET"
    assert response.request.url == http_server + "/users?limit=10"
    assert response.headers["content-type"] == "application/json"
    assert response.json()["request_line"] == "GET /users?limit=10 HTTP/1.1"


async def test_post_json_body(http_server: str, faker: Faker) -> None:
    payload = {"name": faker.name()}

    async with foghttp.AsyncClient() as client:
        response = await client.post(http_server + "/users", json=payload)

    assert response.request.method == "POST"
    assert response.request.url == http_server + "/users"
    assert response.request.headers["content-type"] == "application/json"
    assert response.json()["body"] == orjson.dumps(payload).decode()


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
