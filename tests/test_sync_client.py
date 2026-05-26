from urllib.parse import urlencode

from faker import Faker
import orjson
import pytest

import foghttp
from foghttp.messages import BODY_PARAMETER_CONFLICT
from foghttp.methods import GET, HEAD, POST
from foghttp.status_codes.success import OK
from tests.client_warning_actions import collect_unclosed_client


def test_get_with_params_and_json_response(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        response = client.get(sync_http_server + "/users", params={"limit": 10})

    assert response.status_code == OK
    assert response.request.method == GET
    assert response.request.url == sync_http_server + "/users?limit=10"
    assert response.headers["content-type"] == "application/json"
    assert response.encoding == "utf-8"
    assert response.json()["request_line"] == "GET /users?limit=10 HTTP/1.1"


def test_post_json_body(sync_http_server: str, faker: Faker) -> None:
    payload = {"name": faker.name()}

    with foghttp.Client() as client:
        response = client.post(sync_http_server + "/users", json=payload)

    assert response.request.method == POST
    assert response.request.url == sync_http_server + "/users"
    assert response.request.headers["content-type"] == "application/json"
    assert response.json()["body"] == orjson.dumps(payload).decode()


def test_post_rejects_content_and_json(sync_http_server: str, faker: Faker) -> None:
    content = faker.sentence().encode()
    payload = {"name": faker.name()}

    with foghttp.Client() as client, pytest.raises(ValueError, match=BODY_PARAMETER_CONFLICT):
        client.post(sync_http_server + "/users", content=content, json=payload)


def test_post_form_data_body(sync_http_server: str, faker: Faker) -> None:
    name = faker.name()

    with foghttp.Client() as client:
        response = client.post(
            sync_http_server + "/users",
            data={"name": name, "scope": ["read", "write"]},
        )

    assert response.request.method == POST
    assert response.request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert response.json()["body"] == urlencode({"name": name, "scope": ["read", "write"]}, doseq=True)


def test_post_string_content(sync_http_server: str, faker: Faker) -> None:
    name = faker.name()

    with foghttp.Client() as client:
        response = client.post(sync_http_server + "/users", content=name)

    assert response.request.method == POST
    assert response.json()["body"] == name


def test_send_prepared_request(sync_http_server: str, faker: Faker) -> None:
    payload = {"name": faker.name()}

    with foghttp.Client() as client:
        request = client.build_request(POST, sync_http_server + "/users", json=payload)
        response = client.send(request)

    assert response.request.method == POST
    assert response.request.url == sync_http_server + "/users"
    assert response.request.headers["content-type"] == "application/json"
    assert response.json()["body"] == orjson.dumps(payload).decode()


def test_send_manual_request(sync_http_server: str, faker: Faker) -> None:
    content = faker.sentence().encode()
    request = foghttp.Request(
        POST,
        sync_http_server + "/users",
        headers={"content-type": "text/plain"},
        content=content,
    )

    with foghttp.Client() as client:
        response = client.send(request)

    assert response.request.method == POST
    assert response.request.headers["content-type"] == "text/plain"
    assert response.json()["body"] == content.decode()


def test_send_allows_prepared_request_header_changes(sync_http_server: str, faker: Faker) -> None:
    values = faker.words(nb=2, unique=True)

    with foghttp.Client() as client:
        request = client.build_request(
            GET,
            sync_http_server + "/headers/echo",
            headers=[("x-repeat", values[0])],
        )
        request.headers.add("x-repeat", values[1])
        response = client.send(request)

    assert response.json()["x-repeat"] == values


def test_method_shortcuts(sync_http_server: str, faker: Faker) -> None:
    put_content = faker.sentence().encode()
    patch_content = faker.sentence().encode()

    with foghttp.Client() as client:
        head_response = client.head(sync_http_server + "/users")
        put_response = client.put(sync_http_server + "/users", content=put_content)
        patch_response = client.patch(sync_http_server + "/users", content=patch_content)
        delete_response = client.delete(sync_http_server + "/users")

    assert head_response.status_code == OK
    assert head_response.request.method == HEAD
    assert head_response.content == b""
    assert put_response.json()["request_line"] == "PUT /users HTTP/1.1"
    assert put_response.json()["body"] == put_content.decode()
    assert patch_response.json()["request_line"] == "PATCH /users HTTP/1.1"
    assert patch_response.json()["body"] == patch_content.decode()
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
    with pytest.warns(foghttp.UnclosedClientError, match="FogHTTP client was not closed"):
        collect_unclosed_client(foghttp.Client)


def test_stats_track_requests(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        client.get(sync_http_server)
        stats = client.stats()

    assert stats.total_requests == 1
    assert stats.failed_requests == 0


def test_dump_transport_state(sync_http_server: str) -> None:
    with foghttp.Client() as client:
        client.get(sync_http_server)
        state = client.dump_transport_state()

    assert state.keys() == {
        "active_connections",
        "active_requests",
        "buffered_response_budget_rejections",
        "buffered_response_bytes",
        "connections_aborted",
        "connections_closed",
        "connections_open_failed",
        "connections_opened",
        "connections_reused",
        "idle_connections",
        "peak_pending_requests",
        "pending_requests",
        "pool_acquire_attempts",
        "pool_acquire_immediate",
        "pool_acquire_timeouts",
        "pool_acquire_wait_time_last_ns",
        "pool_acquire_wait_time_max_ns",
        "pool_acquire_wait_time_total_ns",
        "pool_acquire_waited",
        "response_body_aborted",
        "response_body_closed",
        "response_body_reuse_eligible",
        "origins",
    }
    assert state["pending_requests"] == 0
    assert state["origins"][sync_http_server]["active_requests"] == 0
    assert state["origins"][sync_http_server]["last_activity_at_ns"] > 0


def test_dump_transport_state_origin_keys_exclude_request_target_details(
    sync_http_server: str,
    faker: Faker,
) -> None:
    request_url = f"{sync_http_server}/users?token={faker.uuid4()}"

    with foghttp.Client() as client:
        response = client.get(request_url)
        state = client.dump_transport_state()

    assert response.status_code == OK
    assert set(state["origins"]) == {sync_http_server}
