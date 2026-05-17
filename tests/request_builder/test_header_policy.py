from faker import Faker
import pytest

import foghttp
from foghttp.methods import GET, POST


TRANSPORT_MANAGED_HEADER_NAMES = (
    "Host",
    "Content-Length",
    "Transfer-Encoding",
    "Trailer",
    "TE",
    "Connection",
    "Upgrade",
    "Keep-Alive",
    "Proxy-Connection",
)


@pytest.mark.parametrize("header_name", TRANSPORT_MANAGED_HEADER_NAMES)
def test_build_request_rejects_transport_managed_headers(
    faker: Faker,
    header_name: str,
) -> None:
    with foghttp.Client() as client, pytest.raises(ValueError) as exc_info:
        client.build_request(
            GET,
            faker.url(),
            headers={header_name: faker.word()},
        )

    assert header_name in str(exc_info.value)
    assert "managed by FogHTTP transport" in str(exc_info.value)


def test_build_request_rejects_transport_managed_repeated_header(faker: Faker) -> None:
    headers = foghttp.Headers(
        [
            ("Accept", "application/json"),
            ("content-length", "12"),
        ],
    )

    with foghttp.Client() as client, pytest.raises(ValueError) as exc_info:
        client.build_request(GET, faker.url(), headers=headers)

    assert "content-length" in str(exc_info.value)
    assert "managed by FogHTTP transport" in str(exc_info.value)


def test_build_request_allows_semantic_body_headers(faker: Faker) -> None:
    headers = {
        "Content-Encoding": "identity",
        "Content-Type": "text/plain",
    }
    content = faker.sentence()

    with foghttp.Client() as client:
        request = client.build_request(POST, faker.url(), headers=headers, content=content)

    assert request.headers["content-encoding"] == "identity"
    assert request.headers["content-type"] == "text/plain"
    assert request.content == content.encode()


def test_build_request_leaves_framing_headers_to_transport(faker: Faker) -> None:
    payload = {"name": faker.name()}

    with foghttp.Client() as client:
        request = client.build_request(POST, faker.url(), json=payload)

    assert request.headers["content-type"] == "application/json"
    assert "content-length" not in request.headers
    assert "transfer-encoding" not in request.headers


def test_sync_send_rejects_transport_managed_header_added_after_build(faker: Faker) -> None:
    with foghttp.Client() as client:
        request = client.build_request(POST, faker.url(), content=faker.sentence())
        request.headers["Content-Length"] = "10"

        with pytest.raises(ValueError, match="managed by FogHTTP transport"):
            client.send(request)

        stats = client.stats()

    assert stats.total_requests == 0


async def test_async_send_rejects_transport_managed_header_added_after_build(
    faker: Faker,
) -> None:
    async with foghttp.AsyncClient() as client:
        request = client.build_request(POST, faker.url(), content=faker.sentence())
        request.headers["Content-Length"] = "10"

        with pytest.raises(ValueError, match="managed by FogHTTP transport"):
            await client.send(request)

        stats = client.stats()

    assert stats.total_requests == 0
