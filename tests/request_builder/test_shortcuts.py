from faker import Faker
import pytest

import foghttp
from foghttp.methods import DELETE, GET, HEAD, PATCH, POST, PUT, QUERY


SHORTCUT_METHODS = [
    ("get", GET),
    ("head", HEAD),
    ("post", POST),
    ("query", QUERY),
    ("put", PUT),
    ("patch", PATCH),
    ("delete", DELETE),
]

BODYLESS_SHORTCUT_NAMES = [
    "get",
    "head",
]

BODY_KWARGS = [
    pytest.param({"content": b"body"}, id="content"),
    pytest.param({"data": {"field": "value"}}, id="data"),
    pytest.param({"files": {"file": b"body"}}, id="files"),
    pytest.param({"json": {"field": "value"}}, id="json"),
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
    extensions = {"tests.request_id": faker.uuid4()}

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
            extensions=extensions,
        )

    _assert_shortcut_request(
        captured_requests=captured_requests,
        response=response,
        expected_method=expected_method,
        expected_url=f"{url}&trace={trace_value}",
        expected_extensions=extensions,
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
    extensions = {"tests.request_id": faker.uuid4()}

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
            extensions=extensions,
        )

    _assert_shortcut_request(
        captured_requests=captured_requests,
        response=response,
        expected_method=expected_method,
        expected_url=f"{url}&trace={trace_value}",
        expected_extensions=extensions,
    )


@pytest.mark.parametrize("shortcut_name", BODYLESS_SHORTCUT_NAMES)
@pytest.mark.parametrize("body_kwargs", BODY_KWARGS)
def test_sync_get_head_shortcuts_reject_body_parameters(
    shortcut_name: str,
    body_kwargs: dict[str, object],
    faker: Faker,
) -> None:
    with foghttp.Client() as client:
        shortcut = getattr(client, shortcut_name)
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            shortcut(faker.url(), **body_kwargs)


@pytest.mark.parametrize("shortcut_name", BODYLESS_SHORTCUT_NAMES)
@pytest.mark.parametrize("body_kwargs", BODY_KWARGS)
async def test_async_get_head_shortcuts_reject_body_parameters(
    shortcut_name: str,
    body_kwargs: dict[str, object],
    faker: Faker,
) -> None:
    async with foghttp.AsyncClient() as client:
        shortcut = getattr(client, shortcut_name)
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            await shortcut(faker.url(), **body_kwargs)


@pytest.mark.parametrize(
    ("method", "expected_method"),
    [
        pytest.param(GET, GET, id="get"),
        pytest.param(HEAD, HEAD, id="head"),
    ],
)
def test_sync_request_allows_explicit_get_head_body_without_transport(
    method: str,
    expected_method: str,
    faker: Faker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_requests: list[foghttp.Request] = []
    content = faker.sentence().encode()

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
        response = client.request(method, faker.url(), content=content)

    assert response.request.method == expected_method
    assert captured_requests[0].content == content


@pytest.mark.parametrize(
    ("method", "expected_method"),
    [
        pytest.param(GET, GET, id="get"),
        pytest.param(HEAD, HEAD, id="head"),
    ],
)
async def test_async_request_allows_explicit_get_head_body_without_transport(
    method: str,
    expected_method: str,
    faker: Faker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_requests: list[foghttp.Request] = []
    content = faker.sentence().encode()

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
        response = await client.request(method, faker.url(), content=content)

    assert response.request.method == expected_method
    assert captured_requests[0].content == content


def _base_url(faker: Faker) -> str:
    return f"https://{faker.domain_name()}/{faker.uri_path(deep=1)}?debug=1"


def _assert_shortcut_request(
    *,
    captured_requests: list[foghttp.Request],
    response: foghttp.Response,
    expected_method: str,
    expected_url: str,
    expected_extensions: dict[str, object],
) -> None:
    assert len(captured_requests) == 1
    request = captured_requests[0]
    assert response.request.method == expected_method
    assert request.method == expected_method
    assert request.url == expected_url
    assert request.headers["accept"] == "application/json"
    assert request.extensions == expected_extensions
    assert response.request.extensions == expected_extensions


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
            extensions=request.extensions,
        ),
        http_version="HTTP/1.1",
        elapsed=0.0,
    )
