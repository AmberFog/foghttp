import pytest

import foghttp
from foghttp.types import QueryParams


@pytest.mark.parametrize(
    ("params", "expected_url"),
    [
        (
            {"tag": ["rust", "python"]},
            "https://example.com/search?debug=1&tag=rust&tag=python#results",
        ),
        (
            [("tag", "rust"), ("tag", "python"), ("sort", "recent")],
            "https://example.com/search?debug=1&tag=rust&tag=python&sort=recent#results",
        ),
        (
            (("tag", ("rust", "python")), ("sort", "recent")),
            "https://example.com/search?debug=1&tag=rust&tag=python&sort=recent#results",
        ),
        (
            "tag=rust&tag=python",
            "https://example.com/search?debug=1&tag=rust&tag=python#results",
        ),
        (
            "?q=fog+http&reserved=a%26b%3Dc",
            "https://example.com/search?debug=1&q=fog+http&reserved=a%26b%3Dc#results",
        ),
        (
            {"city": "M\u00fcnchen", "phrase": "fog http", "reserved": "a&b=c"},
            "https://example.com/search?debug=1&city=M%C3%BCnchen&phrase=fog+http&reserved=a%26b%3Dc#results",
        ),
    ],
)
def test_build_request_applies_query_params(params: QueryParams, expected_url: str) -> None:
    with foghttp.Client() as client:
        request = client.build_request(
            "GET",
            "https://example.com/search?debug=1#results",
            params=params,
        )

    assert request.url == expected_url


async def test_sync_and_async_build_request_apply_same_query_params_without_transport() -> None:
    params = [
        ("tag", "rust"),
        ("tag", "python"),
        ("q", "fog http"),
    ]
    url = "https://example.com/search?debug=1#results"
    expected_url = "https://example.com/search?debug=1&tag=rust&tag=python&q=fog+http#results"

    with foghttp.Client() as sync_client:
        sync_request = sync_client.build_request("GET", url, params=params)

    async with foghttp.AsyncClient() as async_client:
        async_request = async_client.build_request("GET", url, params=params)

    assert sync_request.url == expected_url
    assert async_request.url == expected_url
