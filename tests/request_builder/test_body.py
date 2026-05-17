from typing import Any

from faker import Faker
import orjson
import pytest

import foghttp
from foghttp.messages import BODY_CONTENT_AND_JSON_CONFLICT
from foghttp.methods import POST


def test_json_body_adds_content_type_when_missing(faker: Faker) -> None:
    payload = {"name": faker.name()}

    with foghttp.Client() as client:
        request = client.build_request(POST, faker.url(), json=payload)

    assert request.content == orjson.dumps(payload)
    assert request.headers["content-type"] == "application/json"


def test_json_body_preserves_explicit_content_type(faker: Faker) -> None:
    content_type = "application/vnd.foghttp+json"
    payload = {"name": faker.name()}

    with foghttp.Client() as client:
        request = client.build_request(
            POST,
            faker.url(),
            headers={"Content-Type": content_type},
            json=payload,
        )

    assert request.content == orjson.dumps(payload)
    assert request.headers["content-type"] == content_type


@pytest.mark.parametrize(
    ("content", "expected_body"),
    [
        ("utf8-\u20ac", "utf8-\u20ac".encode("utf-8")),
        (b"raw-body", b"raw-body"),
        (None, None),
    ],
)
def test_content_body_matrix(content: bytes | str | None, expected_body: bytes | None, faker: Faker) -> None:
    with foghttp.Client() as client:
        request = client.build_request(POST, faker.url(), content=content)

    assert request.content == expected_body
    assert "content-type" not in request.headers


def test_build_request_rejects_content_and_json(faker: Faker) -> None:
    content = faker.sentence().encode()

    with foghttp.Client() as client, pytest.raises(ValueError, match=BODY_CONTENT_AND_JSON_CONFLICT):
        client.build_request(
            POST,
            faker.url(),
            content=content,
            json={"name": faker.name()},
        )


async def test_async_build_request_rejects_content_and_json(faker: Faker) -> None:
    content = faker.sentence().encode()

    async with foghttp.AsyncClient() as client:
        with pytest.raises(ValueError, match=BODY_CONTENT_AND_JSON_CONFLICT):
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
