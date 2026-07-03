from urllib.parse import urlencode

from faker import Faker
import orjson
import pytest

import foghttp
from foghttp.messages import BODY_PARAMETER_CONFLICT
from foghttp.methods import GET, HEAD, POST
from foghttp.status_codes.success import OK
from tests.client_warning_actions import collect_unclosed_client


async def test_get_with_params_and_json_response(http_server: str) -> None:
    async with foghttp.AsyncClient() as client:
        response = await client.get(http_server + "/users", params={"limit": 10})

    assert response.status_code == OK
    assert response.request.method == GET
    assert response.request.url == http_server + "/users?limit=10"
    assert response.headers["content-type"] == "application/json"
    assert response.encoding == "utf-8"
    assert response.json()["request_line"] == "GET /users?limit=10 HTTP/1.1"


async def test_post_json_body(http_server: str, faker: Faker) -> None:
    payload = {"name": faker.name()}

    async with foghttp.AsyncClient() as client:
        response = await client.post(http_server + "/users", json=payload)

    assert response.request.method == POST
    assert response.request.url == http_server + "/users"
    assert response.request.headers["content-type"] == "application/json"
    assert response.json()["body"] == orjson.dumps(payload).decode()


async def test_post_rejects_content_and_json(http_server: str, faker: Faker) -> None:
    content = faker.sentence().encode()
    payload = {"name": faker.name()}

    async with foghttp.AsyncClient() as client:
        with pytest.raises(ValueError, match=BODY_PARAMETER_CONFLICT):
            await client.post(http_server + "/users", content=content, json=payload)


async def test_post_form_data_body(http_server: str, faker: Faker) -> None:
    name = faker.name()

    async with foghttp.AsyncClient() as client:
        response = await client.post(
            http_server + "/users",
            data={"name": name, "scope": ["read", "write"]},
        )

    assert response.request.method == POST
    assert response.request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert response.json()["body"] == urlencode({"name": name, "scope": ["read", "write"]}, doseq=True)


async def test_post_string_content(http_server: str, faker: Faker) -> None:
    name = faker.name()

    async with foghttp.AsyncClient() as client:
        response = await client.post(http_server + "/users", content=name)

    assert response.request.method == POST
    assert response.json()["body"] == name


async def test_send_prepared_request(http_server: str, faker: Faker) -> None:
    payload = {"name": faker.name()}

    async with foghttp.AsyncClient() as client:
        request = client.build_request(POST, http_server + "/users", json=payload)
        response = await client.send(request)

    assert response.request.method == POST
    assert response.request.url == http_server + "/users"
    assert response.request.headers["content-type"] == "application/json"
    assert response.json()["body"] == orjson.dumps(payload).decode()


async def test_send_manual_request(http_server: str, faker: Faker) -> None:
    content = faker.sentence().encode()
    request = foghttp.Request(
        POST,
        http_server + "/users",
        headers={"content-type": "text/plain"},
        content=content,
    )

    async with foghttp.AsyncClient() as client:
        response = await client.send(request)

    assert response.request.method == POST
    assert response.request.headers["content-type"] == "text/plain"
    assert response.json()["body"] == content.decode()


async def test_send_allows_prepared_request_header_changes(http_server: str, faker: Faker) -> None:
    values = faker.words(nb=2, unique=True)

    async with foghttp.AsyncClient() as client:
        request = client.build_request(
            GET,
            http_server + "/headers/echo",
            headers=[("x-repeat", values[0])],
        )
        request.headers.add("x-repeat", values[1])
        response = await client.send(request)

    assert response.json()["x-repeat"] == values


async def test_method_shortcuts(http_server: str, faker: Faker) -> None:
    put_content = faker.sentence().encode()
    patch_content = faker.sentence().encode()

    async with foghttp.AsyncClient() as client:
        head_response = await client.head(http_server + "/users")
        put_response = await client.put(http_server + "/users", content=put_content)
        patch_response = await client.patch(http_server + "/users", content=patch_content)
        delete_response = await client.delete(http_server + "/users")

    assert head_response.status_code == OK
    assert head_response.request.method == HEAD
    assert head_response.content == b""
    assert put_response.json()["request_line"] == "PUT /users HTTP/1.1"
    assert put_response.json()["body"] == put_content.decode()
    assert patch_response.json()["request_line"] == "PATCH /users HTTP/1.1"
    assert patch_response.json()["body"] == patch_content.decode()
    assert delete_response.json()["request_line"] == "DELETE /users HTTP/1.1"


async def test_closed_client_rejects_requests(http_server: str) -> None:
    client = foghttp.AsyncClient()
    await client.aclose()

    with pytest.raises(foghttp.ClientClosedError):
        await client.get(http_server)


async def test_close_is_idempotent() -> None:
    client = foghttp.AsyncClient()

    await client.aclose()
    await client.aclose()


async def test_unclosed_client_warns() -> None:
    with pytest.warns(foghttp.UnclosedClientError, match="FogHTTP client was not closed"):
        collect_unclosed_client(foghttp.AsyncClient)


async def test_stats_track_requests(http_server: str) -> None:
    async with foghttp.AsyncClient() as client:
        await client.get(http_server)
        stats = client.stats()

    assert stats.total_requests == 1
    assert stats.failed_requests == 0


async def test_dump_transport_state(http_server: str) -> None:
    async with foghttp.AsyncClient() as client:
        await client.get(http_server)
        state = client.dump_transport_state()

    assert state.keys() == {
        "active_connections",
        "active_requests",
        "buffered_response_budget_rejections",
        "buffered_response_bytes",
        "connection_acquire_attempts",
        "connection_acquire_immediate",
        "connection_acquire_timeouts",
        "connection_acquire_wait_time_last_ns",
        "connection_acquire_wait_time_max_ns",
        "connection_acquire_wait_time_total_ns",
        "connection_acquire_waited",
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
        "schema_version",
        "snapshot_sequence",
        "origins",
    }
    assert state["pending_requests"] == 0
    assert state["origins"][http_server]["active_requests"] == 0
    assert state["origins"][http_server]["last_activity_at_ns"] > 0
