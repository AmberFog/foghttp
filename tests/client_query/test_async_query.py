from urllib.parse import urlencode

from faker import Faker
import orjson
import pytest

import foghttp
from foghttp.methods import QUERY
from foghttp.status_codes.client_error import NOT_FOUND
from foghttp.status_codes.redirect import TEMPORARY_REDIRECT
from foghttp.status_codes.success import OK
from foghttp.telemetry import TelemetryConfig
from tests.client_query.assertions import assert_query_echo
from tests.client_telemetry.models import RecordingTelemetrySink
from tests.redirect_helpers import SECURITY_HEADERS_PATH


async def test_async_query_supports_json_body(
    http_server: str,
    faker: Faker,
) -> None:
    body = {"filter": faker.sentence()}

    async with foghttp.AsyncClient() as client:
        response = await client.query(
            f"{http_server}{SECURITY_HEADERS_PATH}",
            json=body,
        )

    assert_query_echo(
        response,
        body=orjson.dumps(body).decode(),
        content_type="application/json",
    )


async def test_async_query_supports_form_body(
    http_server: str,
    faker: Faker,
) -> None:
    body = {"filter": faker.word(), "page": faker.random_int(min=1, max=100)}

    async with foghttp.AsyncClient() as client:
        response = await client.query(
            f"{http_server}{SECURITY_HEADERS_PATH}",
            data=body,
        )

    assert_query_echo(
        response,
        body=urlencode(body),
        content_type="application/x-www-form-urlencoded",
    )


async def test_async_query_supports_text_body(
    http_server: str,
    faker: Faker,
) -> None:
    body = faker.sentence()

    async with foghttp.AsyncClient() as client:
        response = await client.query(
            f"{http_server}{SECURITY_HEADERS_PATH}",
            headers={"content-type": "text/plain"},
            content=body,
        )

    assert_query_echo(response, body=body, content_type="text/plain")


async def test_async_query_supports_bytes_body(
    http_server: str,
    faker: Faker,
) -> None:
    body = faker.word().encode()

    async with foghttp.AsyncClient() as client:
        response = await client.query(
            f"{http_server}{SECURITY_HEADERS_PATH}",
            headers={"content-type": "application/octet-stream"},
            content=body,
        )

    assert_query_echo(
        response,
        body=body.decode(),
        content_type="application/octet-stream",
    )


async def test_async_query_preserves_metadata_and_telemetry(
    http_server: str,
    faker: Faker,
) -> None:
    url_secret = faker.sha256()
    body_secret = faker.sha256()
    sink = RecordingTelemetrySink()

    async with foghttp.AsyncClient(telemetry=TelemetryConfig(sink=sink)) as client:
        request = client.build_request(
            QUERY.lower(),
            f"{http_server}/status/{OK}?token={url_secret}",
            json={"filter": body_secret},
        )
        representation = repr(request)
        response = await client.send(request)

    assert request.method == QUERY
    assert response.request.method == QUERY
    assert QUERY in representation
    assert url_secret not in representation
    assert body_secret not in representation
    assert sink.events
    assert {event.method for event in sink.events} == {QUERY}
    assert body_secret not in repr(sink.events)
    assert all(url_secret not in (event.redacted_url or "") for event in sink.events)


async def test_async_query_status_error_preserves_method_and_redacts_sensitive_data(
    http_server: str,
    faker: Faker,
) -> None:
    url_secret = faker.sha256()
    body_secret = faker.sha256()

    async with foghttp.AsyncClient() as client:
        response = await client.request(
            QUERY,
            f"{http_server}/status/{NOT_FOUND}?token={url_secret}",
            headers={"content-type": "text/plain"},
            content=body_secret,
        )

    with pytest.raises(foghttp.HTTPStatusError) as exc_info:
        response.raise_for_status()

    assert str(exc_info.value).startswith(f"{QUERY} ")
    assert url_secret not in str(exc_info.value)
    assert body_secret not in str(exc_info.value)


async def test_async_query_works_with_stream_api(http_server: str, faker: Faker) -> None:
    body = faker.sentence()

    async with (
        foghttp.AsyncClient(follow_redirects=True) as client,
        client.stream(
            QUERY,
            f"{http_server}/redirect/{TEMPORARY_REDIRECT}",
            headers={"content-type": "text/plain"},
            content=body,
        ) as response,
    ):
        payload = orjson.loads(b"".join([chunk async for chunk in response.aiter_bytes()]))

    assert response.request.method == QUERY
    assert payload["request_line"] == f"{QUERY} /final HTTP/1.1"
    assert payload["body"] == body
