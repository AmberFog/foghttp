import pytest

import foghttp
from foghttp.methods import GET
from foghttp.types import QueryParams


REQUEST_URL = "https://example.com/search?debug=1#results"
EXPECTED_URL_PREFIX = "https://example.com/search?debug=1"
EXPECTED_URL_FRAGMENT = "#results"


@pytest.mark.parametrize(
    ("params", "expected_query"),
    [
        ({"tag": ["rust", "python"]}, "tag=rust&tag=python"),
        (
            [("tag", "rust"), ("tag", "python"), ("sort", "recent")],
            "tag=rust&tag=python&sort=recent",
        ),
        (
            (("tag", ("rust", "python")), ("sort", "recent")),
            "tag=rust&tag=python&sort=recent",
        ),
        ("tag=rust&tag=python", "tag=rust&tag=python"),
        ("?q=fog+http&reserved=a%26b%3Dc", "q=fog+http&reserved=a%26b%3Dc"),
        (
            {"city": "M\u00fcnchen", "phrase": "fog http", "reserved": "a&b=c"},
            "city=M%C3%BCnchen&phrase=fog+http&reserved=a%26b%3Dc",
        ),
    ],
)
def test_build_request_applies_query_params(params: QueryParams, expected_query: str) -> None:
    with foghttp.Client() as client:
        request = client.build_request(
            GET,
            REQUEST_URL,
            params=params,
        )

    assert request.url == f"{EXPECTED_URL_PREFIX}&{expected_query}{EXPECTED_URL_FRAGMENT}"


async def test_sync_and_async_build_request_apply_same_query_params_without_transport() -> None:
    params = [
        ("tag", "rust"),
        ("tag", "python"),
        ("q", "fog http"),
    ]
    expected_query = "tag=rust&tag=python&q=fog+http"

    with foghttp.Client() as sync_client:
        sync_request = sync_client.build_request(GET, REQUEST_URL, params=params)

    async with foghttp.AsyncClient() as async_client:
        async_request = async_client.build_request(GET, REQUEST_URL, params=params)

    expected_url = f"{EXPECTED_URL_PREFIX}&{expected_query}{EXPECTED_URL_FRAGMENT}"
    assert sync_request.url == expected_url
    assert async_request.url == expected_url
