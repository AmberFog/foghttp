from faker import Faker
import pytest

import foghttp
from foghttp.methods import DELETE, GET, HEAD, PATCH, POST, PUT


SHORTCUT_METHODS = [
    ("get", GET),
    ("head", HEAD),
    ("post", POST),
    ("put", PUT),
    ("patch", PATCH),
    ("delete", DELETE),
]


@pytest.mark.parametrize(
    ("shortcut_name", "expected_method"),
    SHORTCUT_METHODS,
)
def test_sync_shortcuts_use_request_builder_pipeline_without_transport(
    shortcut_name: str,
    expected_method: str,
    faker: Faker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_requests: list[foghttp.Request] = []
    url = _base_url(faker)
    trace_value = faker.slug()

    def fake_send(
        _client: foghttp.Client,
        request: foghttp.Request,
        *,
        timeout: foghttp.Timeouts | None = None,
    ) -> foghttp.Response:
        captured_requests.append(request)
        return _response_for(request)

    monkeypatch.setattr(foghttp.Client, "send", fake_send)

    with foghttp.Client() as client:
        shortcut = getattr(client, shortcut_name)
        response = shortcut(
            url,
            headers={"Accept": "application/json"},
            params={"trace": trace_value},
        )

    _assert_shortcut_request(
        captured_requests=captured_requests,
        response=response,
        expected_method=expected_method,
        expected_url=f"{url}&trace={trace_value}",
    )


@pytest.mark.parametrize(
    ("shortcut_name", "expected_method"),
    SHORTCUT_METHODS,
)
async def test_async_shortcuts_use_request_builder_pipeline_without_transport(
    shortcut_name: str,
    expected_method: str,
    faker: Faker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_requests: list[foghttp.Request] = []
    url = _base_url(faker)
    trace_value = faker.slug()

    async def fake_send(
        _client: foghttp.AsyncClient,
        request: foghttp.Request,
        *,
        timeout: foghttp.Timeouts | None = None,
    ) -> foghttp.Response:
        captured_requests.append(request)
        return _response_for(request)

    monkeypatch.setattr(foghttp.AsyncClient, "send", fake_send)

    async with foghttp.AsyncClient() as client:
        shortcut = getattr(client, shortcut_name)
        response = await shortcut(
            url,
            headers={"Accept": "application/json"},
            params={"trace": trace_value},
        )

    _assert_shortcut_request(
        captured_requests=captured_requests,
        response=response,
        expected_method=expected_method,
        expected_url=f"{url}&trace={trace_value}",
    )


def _base_url(faker: Faker) -> str:
    return f"https://{faker.domain_name()}/{faker.uri_path(deep=1)}?debug=1"


def _assert_shortcut_request(
    *,
    captured_requests: list[foghttp.Request],
    response: foghttp.Response,
    expected_method: str,
    expected_url: str,
) -> None:
    assert len(captured_requests) == 1
    request = captured_requests[0]
    assert response.request.method == expected_method
    assert request.method == expected_method
    assert request.url == expected_url
    assert request.headers["accept"] == "application/json"


def _response_for(request: foghttp.Request) -> foghttp.Response:
    return foghttp.Response(
        status_code=200,
        headers=foghttp.Headers(),
        content=b"",
        url=request.url,
        request=foghttp.RequestInfo(
            method=request.method,
            url=request.url,
            headers=request.headers,
        ),
        http_version="HTTP/1.1",
        elapsed=0.0,
    )
