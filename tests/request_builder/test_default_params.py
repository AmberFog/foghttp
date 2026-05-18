import foghttp
from foghttp.methods import GET


API_BASE_URL = "https://api.example.com/v1"
DEFAULT_CLIENT = "default"
DEFAULT_TAG = "rust"
REQUEST_TAG = "python"
EXPECTED_SENT_QUERY = f"client={DEFAULT_CLIENT}&tag={DEFAULT_TAG}&tag={REQUEST_TAG}&page=2"
SEARCH_PATH = "/search"
SEARCH_URL = "https://api.example.com/search?debug=1#results"


def test_sync_build_request_applies_default_params() -> None:
    with foghttp.Client(params={"client": DEFAULT_CLIENT}) as client:
        request = client.build_request(GET, SEARCH_URL)

    assert request.url == f"https://api.example.com/search?debug=1&client={DEFAULT_CLIENT}#results"


async def test_async_build_request_applies_default_params() -> None:
    async with foghttp.AsyncClient(params={"client": DEFAULT_CLIENT}) as client:
        request = client.build_request(GET, SEARCH_URL)

    assert request.url == f"https://api.example.com/search?debug=1&client={DEFAULT_CLIENT}#results"


def test_request_params_are_appended_after_default_params() -> None:
    with foghttp.Client(
        base_url=API_BASE_URL,
        params=[
            ("client", DEFAULT_CLIENT),
            ("tag", DEFAULT_TAG),
        ],
    ) as client:
        request = client.build_request(
            GET,
            "search?debug=1#results",
            params=[
                ("tag", REQUEST_TAG),
                ("page", 2),
            ],
        )

    assert (
        request.url == "https://api.example.com/v1/search"
        f"?debug=1&client={DEFAULT_CLIENT}&tag={DEFAULT_TAG}&tag={REQUEST_TAG}&page=2#results"
    )


def test_default_params_accept_raw_query_string_with_leading_question_mark() -> None:
    with foghttp.Client(params="?client=default&tag=rust") as client:
        request = client.build_request(GET, "https://api.example.com/search")

    assert request.url == "https://api.example.com/search?client=default&tag=rust"


def test_default_params_snapshot_user_supplied_params() -> None:
    default_tags = [DEFAULT_TAG]
    default_params = {"tag": default_tags}

    with foghttp.Client(params=default_params) as client:
        default_tags.append(REQUEST_TAG)
        request = client.build_request(GET, "https://api.example.com/search")

    assert default_params == {"tag": [DEFAULT_TAG, REQUEST_TAG]}
    assert request.url == f"https://api.example.com/search?tag={DEFAULT_TAG}"


def test_sync_request_sends_default_params(sync_http_server: str) -> None:
    default_params = {"client": DEFAULT_CLIENT, "tag": [DEFAULT_TAG, REQUEST_TAG]}

    with foghttp.Client(params=default_params) as client:
        response = client.get(f"{sync_http_server}{SEARCH_PATH}", params={"page": 2})

    assert response.request.url == f"{sync_http_server}{SEARCH_PATH}?{EXPECTED_SENT_QUERY}"
    assert response.json()["request_line"] == f"GET {SEARCH_PATH}?{EXPECTED_SENT_QUERY} HTTP/1.1"


async def test_async_request_sends_default_params(http_server: str) -> None:
    default_params = {"client": DEFAULT_CLIENT, "tag": [DEFAULT_TAG, REQUEST_TAG]}

    async with foghttp.AsyncClient(params=default_params) as client:
        response = await client.get(f"{http_server}{SEARCH_PATH}", params={"page": 2})

    assert response.request.url == f"{http_server}{SEARCH_PATH}?{EXPECTED_SENT_QUERY}"
    assert response.json()["request_line"] == f"GET {SEARCH_PATH}?{EXPECTED_SENT_QUERY} HTTP/1.1"
