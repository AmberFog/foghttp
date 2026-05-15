import asyncio
import gc

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
    assert response.encoding == "utf-8"
    assert response.json()["request_line"] == "GET /users?limit=10 HTTP/1.1"


async def test_post_json_body(http_server: str, faker: Faker) -> None:
    payload = {"name": faker.name()}

    async with foghttp.AsyncClient() as client:
        response = await client.post(http_server + "/users", json=payload)

    assert response.request.method == "POST"
    assert response.request.url == http_server + "/users"
    assert response.request.headers["content-type"] == "application/json"
    assert response.json()["body"] == orjson.dumps(payload).decode()


async def test_post_rejects_content_and_json(http_server: str, faker: Faker) -> None:
    content = faker.sentence().encode()
    payload = {"name": faker.name()}

    async with foghttp.AsyncClient() as client:
        with pytest.raises(ValueError, match="pass either content or json"):
            await client.post(http_server + "/users", content=content, json=payload)


async def test_post_string_content(http_server: str, faker: Faker) -> None:
    name = faker.name()

    async with foghttp.AsyncClient() as client:
        response = await client.post(http_server + "/users", content=name)

    assert response.request.method == "POST"
    assert response.json()["body"] == name


async def test_send_prepared_request(http_server: str, faker: Faker) -> None:
    payload = {"name": faker.name()}

    async with foghttp.AsyncClient() as client:
        request = client.build_request("POST", http_server + "/users", json=payload)
        response = await client.send(request)

    assert response.request.method == "POST"
    assert response.request.url == http_server + "/users"
    assert response.request.headers["content-type"] == "application/json"
    assert response.json()["body"] == orjson.dumps(payload).decode()


async def test_send_manual_request(http_server: str, faker: Faker) -> None:
    content = faker.sentence().encode()
    request = foghttp.Request(
        "POST",
        http_server + "/users",
        headers={"content-type": "text/plain"},
        content=content,
    )

    async with foghttp.AsyncClient() as client:
        response = await client.send(request)

    assert response.request.method == "POST"
    assert response.request.headers["content-type"] == "text/plain"
    assert response.json()["body"] == content.decode()


async def test_send_allows_prepared_request_header_changes(http_server: str, faker: Faker) -> None:
    values = faker.words(nb=2, unique=True)

    async with foghttp.AsyncClient() as client:
        request = client.build_request(
            "GET",
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
    assert head_response.request.method == "HEAD"
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
    client = foghttp.AsyncClient()

    with pytest.warns(foghttp.UnclosedClientError, match="was not closed"):
        del client
        gc.collect()


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

    assert state.keys() == {"active_requests", "pending_requests"}
    assert state["pending_requests"] == 0


async def test_pending_request_queue_full(http_server: str) -> None:
    limits = foghttp.Limits(max_active_requests=0, max_pending_requests=0)

    async with foghttp.AsyncClient(limits=limits) as client:
        with pytest.raises(foghttp.TimeoutError, match="request acquire queue is full"):
            await client.get(http_server)

        stats = client.stats()
        assert stats.total_requests == 1
        assert stats.failed_requests == 1
        assert stats.active_requests == 0
        assert stats.pending_requests == 0
        assert stats.pool_acquire_timeouts == 1


async def test_zero_pending_queue_allows_available_connection(http_server: str) -> None:
    limits = foghttp.Limits(max_active_requests=1, max_pending_requests=0)

    async with foghttp.AsyncClient(limits=limits) as client:
        response = await client.get(http_server)

        assert response.status_code == OK
        stats = client.stats()
        assert stats.total_requests == 1
        assert stats.failed_requests == 0
        assert stats.active_requests == 0
        assert stats.pending_requests == 0
        assert stats.pool_acquire_timeouts == 0


async def test_pool_acquire_timeout(http_server: str) -> None:
    limits = foghttp.Limits(max_active_requests=0, max_pending_requests=1)
    timeouts = foghttp.Timeouts(pool=0.001)

    async with foghttp.AsyncClient(limits=limits, timeouts=timeouts) as client:
        with pytest.raises(foghttp.TimeoutError, match="request acquire timeout expired"):
            await client.get(http_server)

        stats = client.stats()
        assert stats.total_requests == 1
        assert stats.failed_requests == 1
        assert stats.active_requests == 0
        assert stats.pending_requests == 0
        assert stats.pool_acquire_timeouts == 1


async def test_pending_requests_are_tracked_while_waiting(http_server: str) -> None:
    limits = foghttp.Limits(max_active_requests=0, max_pending_requests=1)
    timeouts = foghttp.Timeouts(pool=0.2)

    async with foghttp.AsyncClient(limits=limits, timeouts=timeouts) as client:
        task = asyncio.create_task(client.get(http_server))
        try:
            for _attempt in range(200):
                if client.stats().pending_requests == 1:
                    break
                await asyncio.sleep(0.005)

            assert client.stats().pending_requests == 1
            assert client.stats().active_requests == 0
            with pytest.raises(foghttp.TimeoutError, match="request acquire timeout expired"):
                await task
        finally:
            if not task.done():
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

        stats = client.stats()
        assert stats.total_requests == 1
        assert stats.failed_requests == 1
        assert stats.active_requests == 0
        assert stats.pending_requests == 0
        assert stats.pool_acquire_timeouts == 1
