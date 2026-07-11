import asyncio

import pytest

import foghttp
from foghttp.methods import GET
from foghttp.policy import (
    TransportPolicyHooks,
    TransportPolicyRequest,
    TransportPolicyResponse,
)
from foghttp.status_codes.redirect import FOUND
from foghttp.status_codes.success import OK
from tests.client_policy_hooks.requests import send_async_request


@pytest.mark.parametrize("streaming", [False, True], ids=("buffered", "streaming"))
async def test_async_policy_hooks_observe_each_transport_stage(
    http_server: str,
    *,
    streaming: bool,
) -> None:
    events: list[tuple[str, TransportPolicyRequest | TransportPolicyResponse]] = []

    def before_send(request: TransportPolicyRequest) -> None:
        events.append(("before_send", request))

    def on_response_headers(response: TransportPolicyResponse) -> None:
        events.append(("on_response_headers", response))

    def after_response_body(response: TransportPolicyResponse) -> None:
        events.append(("after_response_body", response))

    hooks = TransportPolicyHooks(
        before_send=before_send,
        on_response_headers=on_response_headers,
        after_response_body=after_response_body,
    )
    initial_url = f"{http_server}/redirect/{FOUND}"

    async with foghttp.AsyncClient(follow_redirects=True, policy_hooks=hooks) as client:
        if streaming:
            async with client.stream(GET, initial_url) as response:
                assert response.status_code == OK
                final_url = response.url
        else:
            response = await client.get(initial_url)
            assert response.status_code == OK
            final_url = response.url

    assert [stage for stage, _view in events] == [
        "before_send",
        "on_response_headers",
        "after_response_body",
        "before_send",
        "on_response_headers",
    ]
    first_request = events[0][1]
    redirect_response = events[1][1]
    redirected_request = events[3][1]
    final_response = events[4][1]
    assert isinstance(first_request, TransportPolicyRequest)
    assert first_request == TransportPolicyRequest(GET, initial_url, "empty", 0)
    assert isinstance(redirect_response, TransportPolicyResponse)
    assert redirect_response.request == first_request
    assert redirect_response.status_code == FOUND
    assert events[2][1] == redirect_response
    assert isinstance(redirected_request, TransportPolicyRequest)
    assert redirected_request == TransportPolicyRequest(GET, final_url, "empty", 1)
    assert isinstance(final_response, TransportPolicyResponse)
    assert final_response.request == redirected_request
    assert final_response.status_code == OK


async def test_async_hook_exception_is_propagated(http_server: str) -> None:
    def reject_request(request: TransportPolicyRequest) -> None:
        message = f"blocked {request.method}"
        raise RuntimeError(message)

    hooks = TransportPolicyHooks(before_send=reject_request)

    async with foghttp.AsyncClient(policy_hooks=hooks) as client:
        with pytest.raises(RuntimeError, match="blocked GET"):
            await client.get(http_server)
        stats = client.stats()

    assert stats.pool_acquire_attempts == 0


async def test_async_policy_hook_is_shared_by_concurrent_requests(http_server: str) -> None:
    observed_urls: list[str] = []

    def observe(request: TransportPolicyRequest) -> None:
        observed_urls.append(request.url)

    hooks = TransportPolicyHooks(before_send=observe)
    urls = [f"{http_server}/status/{OK}?request={index}" for index in range(20)]

    async with foghttp.AsyncClient(policy_hooks=hooks) as client:
        responses = await asyncio.gather(*(client.get(url) for url in urls))

    assert all(response.status_code == OK for response in responses)
    assert sorted(observed_urls) == sorted(urls)


@pytest.mark.parametrize("streaming", [False, True], ids=("buffered", "streaming"))
async def test_async_response_hook_failure_releases_transport_resources(
    http_server: str,
    *,
    streaming: bool,
) -> None:
    reject_next_response = True

    def reject_once(response: TransportPolicyResponse) -> None:
        nonlocal reject_next_response
        if reject_next_response:
            reject_next_response = False
            message = f"blocked status {response.status_code}"
            raise RuntimeError(message)

    hooks = TransportPolicyHooks(on_response_headers=reject_once)
    limits = foghttp.Limits(max_active_requests=1, max_connections=1)

    async with foghttp.AsyncClient(policy_hooks=hooks, limits=limits) as client:
        with pytest.raises(RuntimeError, match="blocked status 200"):
            await send_async_request(client, http_server, streaming=streaming)
        stats_after_error = client.stats()
        response = await client.get(http_server)

    assert response.status_code == OK
    assert stats_after_error.total_requests == 1
    assert stats_after_error.failed_requests == 1
    assert stats_after_error.active_requests == 0
    assert stats_after_error.pending_requests == 0
    assert stats_after_error.response_body_aborted == 1
    assert stats_after_error.connections_aborted == 1
