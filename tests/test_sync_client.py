from faker import Faker
import orjson
import pytest

import foghttp
from foghttp.status_codes.success import OK


def test_get_with_params_and_json_response(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        response = client.get(sync_http_server + "/users", params={"limit": 10})

    assert response.status_code == OK
    assert response.request.method == "GET"
    assert response.request.url == sync_http_server + "/users?limit=10"
    assert response.headers["content-type"] == "application/json"
    assert response.json()["request_line"] == "GET /users?limit=10 HTTP/1.1"


def test_post_json_body(sync_http_server: str, faker: Faker) -> None:
    payload = {"name": faker.name()}

    with foghttp.Client() as client:
        response = client.post(sync_http_server + "/users", json=payload)

    assert response.request.method == "POST"
    assert response.request.url == sync_http_server + "/users"
    assert response.request.headers["content-type"] == "application/json"
    assert response.json()["body"] == orjson.dumps(payload).decode()


def test_closed_client_rejects_requests(sync_http_server: str) -> None:
    client = foghttp.Client()
    client.close()

    with pytest.raises(foghttp.ClientClosedError):
        client.get(sync_http_server)


def test_stats_track_requests(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        client.get(sync_http_server)
        stats = client.stats()

    assert stats.total_requests == 1
    assert stats.failed_requests == 0
