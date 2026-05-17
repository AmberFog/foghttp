import pytest

import foghttp
from foghttp.messages import BASE_URL_QUERY_OR_FRAGMENT_UNSUPPORTED
from foghttp.methods import GET


API_BASE_URL = "https://api.example.com/v1"
API_BASE_URL_WITH_SLASH = f"{API_BASE_URL}/"
API_USERS_URL = f"{API_BASE_URL}/users"
ROOT_USERS_URL = "https://api.example.com/users"
RELATIVE_USERS_URL = "users"
USERS_URL_WITH_QUERY_AND_FRAGMENT = "users?debug=1#profile"


@pytest.mark.parametrize("base_url", [API_BASE_URL, API_BASE_URL_WITH_SLASH])
def test_sync_build_request_resolves_relative_url_against_base_url(base_url: str) -> None:
    with foghttp.Client(base_url=base_url) as client:
        request = client.build_request(
            GET,
            USERS_URL_WITH_QUERY_AND_FRAGMENT,
            params={"page": 2},
        )

    assert request.url == f"{API_USERS_URL}?debug=1&page=2#profile"


async def test_async_build_request_resolves_relative_url_against_base_url() -> None:
    async with foghttp.AsyncClient(base_url=foghttp.URL(API_BASE_URL)) as client:
        request = client.build_request(
            GET,
            USERS_URL_WITH_QUERY_AND_FRAGMENT,
            params={"page": 2},
        )

    assert request.url == f"{API_USERS_URL}?debug=1&page=2#profile"


def test_base_url_allows_root_relative_paths_to_escape_base_path() -> None:
    with foghttp.Client(base_url=API_BASE_URL) as client:
        request = client.build_request(GET, "/users")

    assert request.url == ROOT_USERS_URL


def test_absolute_request_url_ignores_base_url() -> None:
    with foghttp.Client(base_url="https://internal.example.com/v1") as client:
        request = client.build_request(GET, ROOT_USERS_URL)

    assert request.url == ROOT_USERS_URL


def test_build_request_with_base_url_does_not_create_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    def create_raw_client_probe(*_args: object, **_kwargs: object) -> object:
        msg = "build_request() must not create a RawClient"
        raise AssertionError(msg)

    monkeypatch.setattr("foghttp._client.core.create_raw_client", create_raw_client_probe)

    with foghttp.Client(base_url=API_BASE_URL) as client:
        request = client.build_request(GET, RELATIVE_USERS_URL)

    assert request.url == API_USERS_URL


def test_sync_request_sends_relative_url_against_base_url(sync_http_server: str) -> None:
    with foghttp.Client(base_url=sync_http_server) as client:
        response = client.get(RELATIVE_USERS_URL, params={"limit": 10})

    assert response.request.url == f"{sync_http_server}/users?limit=10"
    assert response.json()["request_line"] == "GET /users?limit=10 HTTP/1.1"


async def test_async_request_sends_relative_url_against_base_url(http_server: str) -> None:
    async with foghttp.AsyncClient(base_url=http_server) as client:
        response = await client.get(RELATIVE_USERS_URL, params={"limit": 10})

    assert response.request.url == f"{http_server}/users?limit=10"
    assert response.json()["request_line"] == "GET /users?limit=10 HTTP/1.1"


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.example.com/v1?token=secret",
        "https://api.example.com/v1#users",
    ],
)
def test_base_url_rejects_query_and_fragment(base_url: str) -> None:
    with pytest.raises(ValueError, match=BASE_URL_QUERY_OR_FRAGMENT_UNSUPPORTED):
        foghttp.Client(base_url=base_url)
