import asyncio
import json

import pytest

import foghttp


OK_STATUS_CODE = 200


async def _read_request(reader: asyncio.StreamReader) -> tuple[str, bytes]:
    head = await reader.readuntil(b"\r\n\r\n")
    headers = head.decode("iso-8859-1")
    length = 0
    for line in headers.split("\r\n"):
        name, _, value = line.partition(":")
        if name.lower() == "content-length":
            length = int(value.strip())
    body = await reader.readexactly(length) if length else b""
    return headers, body


@pytest.fixture
async def http_server():
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        headers, body = await _read_request(reader)
        request_line = headers.splitlines()[0]
        payload = json.dumps(
            {
                "request_line": request_line,
                "body": body.decode(),
            },
        ).encode()
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"content-type: application/json\r\n"
            + f"content-length: {len(payload)}\r\n".encode()
            + b"connection: close\r\n\r\n"
            + payload,
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        host, port = server.sockets[0].getsockname()
        yield f"http://{host}:{port}"
    finally:
        server.close()
        await server.wait_closed()


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
