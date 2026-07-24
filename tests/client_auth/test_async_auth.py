import asyncio
from base64 import b64encode
from contextlib import suppress
from threading import Barrier, Event

from faker import Faker
import pytest

import foghttp
from foghttp.auth import AuthRequest
from foghttp.methods import GET
from foghttp.status_codes.redirect import FOUND
from tests.client_retry.server import start_retry_test_server
from tests.redirect_helpers import SECURITY_HEADERS_PATH, header_values, redirect_to_location_url


@pytest.mark.parametrize("streaming", [False, True], ids=("buffered", "streaming"))
async def test_async_basic_auth_is_applied_for_each_transport_mode(
    http_server: str,
    faker: Faker,
    *,
    streaming: bool,
) -> None:
    username = faker.user_name()
    password = faker.password()
    expected = _basic_authorization(username, password)
    url = f"{http_server}{SECURITY_HEADERS_PATH}"
    async with foghttp.AsyncClient(auth=(username, password)) as client:
        if streaming:
            async with client.stream(GET, url) as response:
                assert response.request.headers["authorization"] == expected
        else:
            response = await client.get(url)
            assert response.request.headers["authorization"] == expected


async def test_async_callable_auth_refreshes_on_same_origin_redirect(
    http_server: str,
) -> None:
    requests: list[AuthRequest] = []

    def authenticate(request: AuthRequest) -> dict[str, str]:
        requests.append(request)
        return {"Authorization": f"Bearer hop-{request.redirect_hop}"}

    location = f"{http_server}{SECURITY_HEADERS_PATH}"
    url = redirect_to_location_url(http_server, status_code=FOUND, location=location)
    async with foghttp.AsyncClient(auth=authenticate, follow_redirects=True) as client:
        response = await client.get(url)

    assert [request.redirect_hop for request in requests] == [0, 1]
    assert header_values(response.json(), "authorization") == ["Bearer hop-1"]


async def test_async_callable_auth_is_disabled_after_cross_origin_redirect(
    http_server: str,
    secondary_http_server: str,
) -> None:
    requests: list[AuthRequest] = []
    default_credential = "default-vendor-proof"
    managed_credential = "auth-vendor-proof"

    def authenticate(request: AuthRequest) -> dict[str, str]:
        requests.append(request)
        return {
            "Authorization": "Bearer secret",
            "X-Vendor-Proof": managed_credential,
        }

    location = f"{secondary_http_server}{SECURITY_HEADERS_PATH}"
    url = redirect_to_location_url(http_server, status_code=FOUND, location=location)
    async with foghttp.AsyncClient(
        headers={"X-Vendor-Proof": default_credential},
        auth=authenticate,
        follow_redirects=True,
    ) as client:
        response = await client.get(url)

    assert [request.redirect_hop for request in requests] == [0]
    assert response.history[0].request.headers["x-vendor-proof"] == managed_credential
    assert header_values(response.json(), "authorization") == []
    assert "x-vendor-proof" not in response.request.headers
    representation = repr((response.request, response.history))
    assert "Bearer secret" not in representation
    assert managed_credential not in representation
    assert default_credential not in representation


async def test_async_cross_origin_redirect_strips_inactive_auth_header(
    http_server: str,
    secondary_http_server: str,
) -> None:
    default_credential = "default-vendor-proof"

    def authenticate(request: AuthRequest) -> dict[str, str] | None:
        if request.redirect_hop == 0:
            return {"X-Vendor-Proof": "auth-vendor-proof"}
        return None

    final_location = f"{secondary_http_server}/headers/echo"
    cross_origin_redirect = redirect_to_location_url(
        http_server,
        status_code=FOUND,
        location=final_location,
    )
    url = redirect_to_location_url(
        http_server,
        status_code=FOUND,
        location=cross_origin_redirect,
    )
    async with foghttp.AsyncClient(
        headers={"X-Vendor-Proof": default_credential},
        auth=authenticate,
        follow_redirects=True,
    ) as client:
        response = await client.get(url)

    second_hop = response.history[1].request
    assert second_hop.headers["x-vendor-proof"] == default_credential
    assert default_credential not in repr(second_hop)
    assert response.json().get("x-vendor-proof", []) == []


async def test_async_callable_auth_keeps_request_state_isolated_under_overlap(
    http_server: str,
) -> None:
    urls = [f"{http_server}{SECURITY_HEADERS_PATH}?request={index}" for index in range(2)]
    request_ids = {url: index for index, url in enumerate(urls)}
    overlap = Barrier(len(urls))
    observed: dict[str, object] = {}

    def authenticate(request: AuthRequest) -> dict[str, str]:
        overlap.wait(timeout=5.0)
        request_id = request.extensions["tests.request_id"]
        observed[request.url] = request_id
        return {"Authorization": f"Bearer request-{request_id}"}

    async with foghttp.AsyncClient(
        auth=authenticate,
        runtime="dedicated",
        runtime_workers=2,
    ) as client:
        responses = await asyncio.gather(
            *(client.get(url, extensions={"tests.request_id": request_ids[url]}) for url in urls),
        )

    assert observed == request_ids
    assert [header_values(response.json(), "authorization") for response in responses] == [
        [f"Bearer request-{request_ids[url]}"] for url in urls
    ]


@pytest.mark.parametrize("streaming", [False, True], ids=("buffered", "streaming"))
async def test_async_close_does_not_preempt_running_auth_hook(*, streaming: bool) -> None:
    entered = Event()
    release = Event()
    finished = Event()
    policy_hook_called = Event()

    def authenticate(_request: AuthRequest) -> None:
        entered.set()
        release.wait(timeout=5.0)
        finished.set()

    def before_send(_request: foghttp.TransportPolicyRequest) -> None:
        policy_hook_called.set()

    async def send(client: foghttp.AsyncClient, url: str) -> None:
        if streaming:
            async with client.stream(GET, url):
                pass
        else:
            await client.get(url)

    with start_retry_test_server() as server:
        client = foghttp.AsyncClient(
            auth=authenticate,
            policy_hooks=foghttp.TransportPolicyHooks(before_send=before_send),
        )
        raw_client = client._raw_client()  # noqa: SLF001
        request = asyncio.create_task(send(client, server.url))
        callback_finished = False
        try:
            assert await asyncio.to_thread(entered.wait, 1.0)
            await client.aclose()

            with pytest.raises(asyncio.CancelledError):
                await request
            assert not finished.is_set()
        finally:
            release.set()
            callback_finished = await asyncio.to_thread(finished.wait, 1.0)
            await client.aclose()
            if not request.done():
                request.cancel()
            with suppress(asyncio.CancelledError):
                await request

        assert raw_client.stats().pool_acquire_attempts == 0
        assert not policy_hook_called.is_set()
        assert server.snapshot().requests == ()

    assert callback_finished


@pytest.mark.parametrize("streaming", [False, True], ids=("buffered", "streaming"))
async def test_async_auth_hook_receives_request_extensions(
    http_server: str,
    *,
    streaming: bool,
) -> None:
    observed: list[foghttp.RequestExtensions] = []

    def authenticate(request: AuthRequest) -> None:
        observed.append(request.extensions)

    extensions = {"tests.tenant": "tenant-1"}
    async with foghttp.AsyncClient(auth=authenticate) as client:
        if streaming:
            async with client.stream(GET, http_server, extensions=extensions):
                pass
        else:
            await client.get(http_server, extensions=extensions)

    assert observed == [foghttp.RequestExtensions(extensions)]


def _basic_authorization(username: str, password: str) -> str:
    token = b64encode(f"{username}:{password}".encode()).decode("ascii")
    return f"Basic {token}"
