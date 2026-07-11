from faker import Faker
import orjson

import foghttp
from foghttp.methods import QUERY


async def test_sync_and_async_build_query_with_same_body(faker: Faker) -> None:
    payload = {"filter": faker.sentence()}
    url = faker.url()

    with foghttp.Client() as sync_client:
        sync_request = sync_client.build_request(QUERY.lower(), url, json=payload)

    async with foghttp.AsyncClient() as async_client:
        async_request = async_client.build_request(QUERY.lower(), url, json=payload)

    expected_body = orjson.dumps(payload)
    assert sync_request.method == QUERY
    assert async_request.method == QUERY
    assert sync_request.headers["content-type"] == "application/json"
    assert async_request.headers["content-type"] == "application/json"
    assert sync_request.content == expected_body
    assert async_request.content == expected_body


def test_query_raw_content_does_not_invent_media_type(faker: Faker) -> None:
    with foghttp.Client() as client:
        request = client.build_request(QUERY, faker.url(), content=faker.sentence())

    assert "content-type" not in request.headers
