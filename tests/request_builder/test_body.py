from datetime import UTC, datetime
import io
from typing import Any
from uuid import UUID

from faker import Faker
import pytest

import foghttp
from foghttp._request_body import request_body
from foghttp.messages import BODY_CONTENT_UNSUPPORTED, BODY_DATA_UNSUPPORTED, BODY_PARAMETER_CONFLICT
from foghttp.methods import POST
from foghttp.types import RequestData
from tests.client_multipart.sources import AsyncChunks, ClosingBytesFile, SyncChunks, TrackedFactory
from tests.request_builder.models import JsonPayload


def test_json_body_adds_content_type_when_missing(faker: Faker) -> None:
    payload = {"name": "Ada"}

    with foghttp.Client() as client:
        request = client.build_request(POST, faker.url(), json=payload)

    assert request.content == b'{"name":"Ada"}'
    assert request.headers["content-type"] == "application/json"


def test_json_body_preserves_explicit_content_type(faker: Faker) -> None:
    content_type = "application/vnd.foghttp+json"
    payload = {"name": "Ada"}

    with foghttp.Client() as client:
        request = client.build_request(
            POST,
            faker.url(),
            headers={"Content-Type": content_type},
            json=payload,
        )

    assert request.content == b'{"name":"Ada"}'
    assert request.headers["content-type"] == content_type


@pytest.mark.parametrize(
    ("payload", "expected_body"),
    [
        pytest.param("\u00e9 \u20ac \U0001f680", b'"\xc3\xa9 \xe2\x82\xac \xf0\x9f\x9a\x80"', id="unicode"),
        pytest.param('"\\\b\f\n\r\t\x00', b'"\\"\\\\\\b\\f\\n\\r\\t\\u0000"', id="escapes"),
        pytest.param(
            {"items": [None, True, False, {}, []], "pair": (1, 2)},
            b'{"items":[null,true,false,{},[]],"pair":[1,2]}',
            id="containers",
        ),
        pytest.param(
            [-7, 1.25, 1e-7, 9007199254740993, 18446744073709551615],
            b"[-7,1.25,1e-7,9007199254740993,18446744073709551615]",
            id="numbers",
        ),
        pytest.param([float("nan"), float("inf"), -float("inf")], b"[null,null,null]", id="non-finite"),
        pytest.param(
            JsonPayload(
                datetime(2026, 1, 2, 3, 4, 5, 123456, tzinfo=UTC),
                UUID("12345678-1234-5678-1234-567812345678"),
            ),
            b'{"created_at":"2026-01-02T03:04:05.123456+00:00","identifier":"12345678-1234-5678-1234-567812345678"}',
            id="dataclass-datetime-uuid",
        ),
    ],
)
async def test_json_body_preserves_wire_format(payload: Any, expected_body: bytes, faker: Faker) -> None:
    with foghttp.Client() as client:
        request = client.build_request(POST, faker.url(), json=payload)
    async with foghttp.AsyncClient() as async_client:
        async_request = async_client.build_request(POST, faker.url(), json=payload)

    assert request.content == expected_body
    assert async_request.content == expected_body


@pytest.mark.parametrize("payload", [object(), b"bytes", {1: "value"}, 2**64, "\ud800"])
async def test_json_body_rejects_invalid_values_with_type_error(payload: Any, faker: Faker) -> None:
    with foghttp.Client() as client, pytest.raises(TypeError):
        client.build_request(POST, faker.url(), json=payload)
    async with foghttp.AsyncClient() as async_client:
        with pytest.raises(TypeError):
            async_client.build_request(POST, faker.url(), json=payload)


@pytest.mark.parametrize(
    ("content", "expected_body"),
    [
        ("utf8-\u20ac", "utf8-\u20ac".encode("utf-8")),
        ("", b""),
        (b"raw-body", b"raw-body"),
        (b"", b""),
        (None, None),
    ],
)
def test_content_body_matrix(content: bytes | str | None, expected_body: bytes | None, faker: Faker) -> None:
    with foghttp.Client() as client:
        request = client.build_request(POST, faker.url(), content=content)

    assert request.content == expected_body
    assert "content-type" not in request.headers
    assert "content-length" not in request.headers
    assert "transfer-encoding" not in request.headers


@pytest.mark.parametrize("content", [bytearray(b"body"), memoryview(b"body")])
def test_build_request_rejects_bytes_like_iterables(content: object, faker: Faker) -> None:
    with foghttp.Client() as client, pytest.raises(TypeError, match=BODY_CONTENT_UNSUPPORTED):
        client.build_request(POST, faker.url(), content=content)


def test_build_request_rejects_content_and_json(faker: Faker) -> None:
    content = faker.sentence().encode()

    with foghttp.Client() as client, pytest.raises(ValueError, match=BODY_PARAMETER_CONFLICT):
        client.build_request(
            POST,
            faker.url(),
            content=content,
            json={"name": faker.name()},
        )


def test_build_request_accepts_streaming_content(faker: Faker) -> None:
    content: Any = iter([faker.sentence().encode()])

    with foghttp.Client() as client:
        request = client.build_request(POST, faker.url(), content=content)

    body = request_body(request)
    assert request.content is None
    assert body.stream is content
    assert body.replayable is False


def test_unsent_prepared_content_provider_remains_caller_owned(faker: Faker) -> None:
    content = io.BytesIO(b"unsent")

    with foghttp.Client() as client:
        client.build_request(POST, faker.url(), content=content)

    assert content.closed is False
    content.close()


def test_build_request_accepts_replayable_streaming_factory(faker: Faker) -> None:
    def content() -> Any:
        return iter([faker.sentence().encode()])

    with foghttp.Client() as client:
        request = client.build_request(POST, faker.url(), content=content)

    body = request_body(request)
    assert request.content is None
    assert body.stream is content
    assert body.replayable is True


async def test_async_build_request_rejects_content_and_json(faker: Faker) -> None:
    content = faker.sentence().encode()

    async with foghttp.AsyncClient() as client:
        with pytest.raises(ValueError, match=BODY_PARAMETER_CONFLICT):
            client.build_request(
                POST,
                faker.url(),
                content=content,
                json={"name": faker.name()},
            )


@pytest.mark.parametrize(
    ("json_body", "expected_body"),
    [
        (None, None),
        (False, b"false"),
        (0, b"0"),
        ({}, b"{}"),
        ([], b"[]"),
    ],
)
def test_json_body_none_is_not_a_body(json_body: Any, expected_body: bytes | None, faker: Faker) -> None:
    with foghttp.Client() as client:
        request = client.build_request(POST, faker.url(), json=json_body)

    assert request.content == expected_body
    if json_body is None:
        assert "content-type" not in request.headers
    else:
        assert request.headers["content-type"] == "application/json"
        assert "content-length" not in request.headers
        assert "transfer-encoding" not in request.headers


@pytest.mark.parametrize(
    ("data", "expected_body"),
    [
        (
            {"grant_type": "client credentials", "scope": ["read", "write"]},
            b"grant_type=client+credentials&scope=read&scope=write",
        ),
        (
            [("scope", "read"), ("scope", "write"), ("reserved", "a&b=c")],
            b"scope=read&scope=write&reserved=a%26b%3Dc",
        ),
        (
            (("city", "M\u00fcnchen"), ("enabled", True), ("count", 2)),
            b"city=M%C3%BCnchen&enabled=True&count=2",
        ),
        ({}, b""),
        ([], b""),
    ],
)
def test_form_data_body_matrix(data: RequestData, expected_body: bytes, faker: Faker) -> None:
    with foghttp.Client() as client:
        request = client.build_request(POST, faker.url(), data=data)

    assert request.content == expected_body
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert "content-length" not in request.headers
    assert "transfer-encoding" not in request.headers


@pytest.mark.parametrize(
    ("data", "expected_body"),
    [
        ("grant_type=client_credentials&scope=read", b"grant_type=client_credentials&scope=read"),
        (b"raw-form-body", b"raw-form-body"),
    ],
)
def test_raw_data_body_matrix(data: RequestData, expected_body: bytes, faker: Faker) -> None:
    with foghttp.Client() as client:
        request = client.build_request(POST, faker.url(), data=data)

    assert request.content == expected_body
    assert "content-type" not in request.headers
    assert "content-length" not in request.headers
    assert "transfer-encoding" not in request.headers


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(ClosingBytesFile(b"file-like"), id="file-like"),
        pytest.param(SyncChunks((b"sync-provider",)), id="sync-provider"),
        pytest.param(AsyncChunks((b"async-provider",)), id="async-provider"),
        pytest.param(TrackedFactory(lambda: SyncChunks((b"factory-product",))), id="factory"),
    ],
)
async def test_data_rejects_providers_without_taking_ownership(data: Any, faker: Faker) -> None:
    with foghttp.Client() as client, pytest.raises(TypeError, match=BODY_DATA_UNSUPPORTED):
        client.build_request(POST, faker.url(), data=data)

    assert data.close_calls == 0
    if isinstance(data, TrackedFactory):
        assert data.calls == 0
    if isinstance(data, AsyncChunks):
        await data.aclose()
    else:
        data.close()


def test_form_data_body_preserves_explicit_content_type(faker: Faker) -> None:
    content_type = "application/vnd.foghttp.form"

    with foghttp.Client() as client:
        request = client.build_request(
            POST,
            faker.url(),
            headers={"content-type": content_type},
            data={"name": faker.name()},
        )

    assert request.headers["content-type"] == content_type


@pytest.mark.parametrize(
    "body_kwargs",
    [
        {"content": b"raw body", "data": {"name": "Ada Lovelace"}},
        {"data": {"name": "Ada Lovelace"}, "json": {"name": "Ada Lovelace"}},
        {"content": b"raw body", "data": {"name": "Ada Lovelace"}, "json": {"name": "Ada Lovelace"}},
    ],
)
def test_build_request_rejects_multiple_body_sources(body_kwargs: dict[str, object], faker: Faker) -> None:
    with foghttp.Client() as client, pytest.raises(ValueError, match=BODY_PARAMETER_CONFLICT):
        client.build_request(POST, faker.url(), **body_kwargs)


def test_build_request_rejects_non_form_data_sequence(faker: Faker) -> None:
    data: Any = iter([("name", faker.name())])

    with foghttp.Client() as client, pytest.raises(TypeError, match=BODY_DATA_UNSUPPORTED):
        client.build_request(POST, faker.url(), data=data)
