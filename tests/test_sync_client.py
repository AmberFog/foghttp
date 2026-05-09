import gc

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
    assert response.encoding == "utf-8"
    assert response.json()["request_line"] == "GET /users?limit=10 HTTP/1.1"


def test_post_json_body(sync_http_server: str, faker: Faker) -> None:
    payload = {"name": faker.name()}

    with foghttp.Client() as client:
        response = client.post(sync_http_server + "/users", json=payload)

    assert response.request.method == "POST"
    assert response.request.url == sync_http_server + "/users"
    assert response.request.headers["content-type"] == "application/json"
    assert response.json()["body"] == orjson.dumps(payload).decode()


def test_post_rejects_content_and_json(sync_http_server: str) -> None:
    with foghttp.Client() as client, pytest.raises(ValueError, match="pass either content or json"):
        client.post(sync_http_server + "/users", content=b"raw", json={"name": "Ada"})


def test_post_string_content(sync_http_server: str, faker: Faker) -> None:
    name = faker.name()

    with foghttp.Client() as client:
        response = client.post(sync_http_server + "/users", content=name)

    assert response.request.method == "POST"
    assert response.json()["body"] == name


def test_method_shortcuts(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        head_response = client.head(sync_http_server + "/users")
        put_response = client.put(sync_http_server + "/users", content=b"put")
        patch_response = client.patch(sync_http_server + "/users", content=b"patch")
        delete_response = client.delete(sync_http_server + "/users")

    assert head_response.status_code == OK
    assert head_response.request.method == "HEAD"
    assert head_response.content == b""
    assert put_response.json()["request_line"] == "PUT /users HTTP/1.1"
    assert put_response.json()["body"] == "put"
    assert patch_response.json()["request_line"] == "PATCH /users HTTP/1.1"
    assert patch_response.json()["body"] == "patch"
    assert delete_response.json()["request_line"] == "DELETE /users HTTP/1.1"


def test_closed_client_rejects_requests(sync_http_server: str) -> None:
    client = foghttp.Client()
    client.close()

    with pytest.raises(foghttp.ClientClosedError):
        client.get(sync_http_server)


def test_close_is_idempotent() -> None:
    client = foghttp.Client()

    client.close()
    client.close()


def test_unclosed_client_warns() -> None:
    client = foghttp.Client()

    with pytest.warns(foghttp.UnclosedClientError, match="was not closed"):
        del client
        gc.collect()


def test_stats_track_requests(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        client.get(sync_http_server)
        stats = client.stats()

    assert stats.total_requests == 1
    assert stats.failed_requests == 0


def test_dump_pool_state(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        client.get(sync_http_server)
        state = client.dump_pool_state()

    assert state.keys() == {"active_connections", "idle_connections", "pending_acquires"}
    assert state["pending_acquires"] == 0


def test_pending_acquire_queue_full(sync_http_server: str) -> None:
    limits = foghttp.Limits(max_pending_acquires=0)

    with foghttp.Client(limits=limits) as client:
        with pytest.raises(foghttp.TimeoutError, match="connection acquire queue is full"):
            client.get(sync_http_server)

        assert client.stats().pool_timeouts == 1


def test_pool_acquire_timeout(sync_http_server: str) -> None:
    limits = foghttp.Limits(max_connections=0, max_pending_acquires=1)
    timeouts = foghttp.Timeouts(pool=0.001)

    with foghttp.Client(limits=limits, timeouts=timeouts) as client:
        with pytest.raises(foghttp.TimeoutError, match="connection acquire timeout expired"):
            client.get(sync_http_server)

        assert client.stats().pool_timeouts == 1
