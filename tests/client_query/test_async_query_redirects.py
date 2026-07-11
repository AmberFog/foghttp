from urllib.parse import urlsplit

from faker import Faker
import pytest

import foghttp
from foghttp.methods import GET, QUERY
from foghttp.status_codes.redirect import SEE_OTHER
from tests.client_query.assertions import (
    assert_cross_origin_query_is_sanitized,
    assert_query_redirect,
)
from tests.client_query.constants import QUERY_PRESERVING_REDIRECT_PARAMS
from tests.redirect_helpers import (
    REDIRECT_SECURITY_HEADERS,
    SECURITY_HEADERS_PATH,
    header_values,
    redirect_to_location_url,
)


@pytest.mark.parametrize("status_code", QUERY_PRESERVING_REDIRECT_PARAMS)
async def test_async_query_redirect_preserves_method_and_body(
    http_server: str,
    faker: Faker,
    status_code: int,
) -> None:
    body = faker.sentence()

    async with foghttp.AsyncClient(follow_redirects=True) as client:
        response = await client.request(
            QUERY,
            f"{http_server}/redirect/{status_code}",
            headers={"content-type": "text/plain"},
            content=body,
        )

    assert_query_redirect(
        response,
        base_url=http_server,
        status_code=status_code,
        body=body,
    )


async def test_async_query_see_other_rewrites_to_get(
    http_server: str,
    faker: Faker,
) -> None:
    location = f"{http_server}{SECURITY_HEADERS_PATH}"
    url = redirect_to_location_url(http_server, status_code=SEE_OTHER, location=location)
    authorization = f"Bearer {faker.sha256()}"

    async with foghttp.AsyncClient(follow_redirects=True) as client:
        response = await client.request(
            QUERY,
            url,
            headers={
                "authorization": authorization,
                "content-encoding": "identity",
                "content-type": "text/plain",
            },
            content=faker.sentence(),
        )

    payload = response.json()
    assert response.request.method == GET
    assert response.history[0].status_code == SEE_OTHER
    assert response.history[0].request.method == QUERY
    assert payload["request_line"] == f"{GET} {SECURITY_HEADERS_PATH} HTTP/1.1"
    assert payload["body"] == ""
    assert header_values(payload, "authorization") == [authorization]
    assert header_values(payload, "content-encoding") == []
    assert header_values(payload, "content-type") == []


async def test_async_query_see_other_drops_non_replayable_body(
    http_server: str,
    faker: Faker,
) -> None:
    async with foghttp.AsyncClient(follow_redirects=True) as client:
        response = await client.request(
            QUERY,
            f"{http_server}/redirect/{SEE_OTHER}",
            headers={"content-type": "application/octet-stream"},
            content=iter((faker.word().encode(),)),
        )

    assert response.request.method == GET
    assert response.history[0].status_code == SEE_OTHER
    assert response.history[0].request.method == QUERY
    assert response.json()["request_line"] == f"{GET} /final HTTP/1.1"
    assert response.json()["body"] == ""


@pytest.mark.parametrize("status_code", QUERY_PRESERVING_REDIRECT_PARAMS)
async def test_async_query_redirect_rejects_non_replayable_body(
    http_server: str,
    faker: Faker,
    status_code: int,
) -> None:
    async with foghttp.AsyncClient(follow_redirects=True) as client:
        with pytest.raises(foghttp.RequestError, match="non-replayable request body"):
            await client.request(
                QUERY,
                f"{http_server}/redirect/{status_code}",
                headers={"content-type": "application/octet-stream"},
                content=iter((faker.word().encode(),)),
            )

        stats = client.stats()

    assert stats.total_requests == 1
    assert stats.failed_requests == 1
    assert stats.active_requests == 0


@pytest.mark.parametrize("status_code", QUERY_PRESERVING_REDIRECT_PARAMS)
async def test_cross_origin_async_query_redirect_is_sanitized(
    http_server: str,
    secondary_http_server: str,
    faker: Faker,
    status_code: int,
) -> None:
    location = f"{secondary_http_server}{SECURITY_HEADERS_PATH}"
    url = redirect_to_location_url(http_server, status_code=status_code, location=location)

    async with foghttp.AsyncClient(follow_redirects=True) as client:
        response = await client.request(
            QUERY,
            url,
            headers={
                **REDIRECT_SECURITY_HEADERS,
                "content-encoding": "identity",
                "content-type": "text/plain",
            },
            content=faker.sentence(),
        )

    assert_cross_origin_query_is_sanitized(
        response.json(),
        host=urlsplit(secondary_http_server).netloc,
    )
