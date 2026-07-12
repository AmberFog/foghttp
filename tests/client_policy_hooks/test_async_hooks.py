import asyncio
from threading import Barrier

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
    extensions = {"tests.request_id": initial_url}
    expected_extensions = foghttp.RequestExtensions(extensions)

    async with foghttp.AsyncClient(follow_redirects=True, policy_hooks=hooks) as client:
        if streaming:
            async with client.stream(GET, initial_url, extensions=extensions) as response:
                assert response.status_code == OK
                final_url = response.url
        else:
            response = await client.get(initial_url, extensions=extensions)
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
    assert first_request == TransportPolicyRequest(GET, initial_url, "empty", 0, expected_extensions)
    assert isinstance(redirect_response, TransportPolicyResponse)
    assert redirect_response.request == first_request
    assert redirect_response.status_code == FOUND
    assert events[2][1] == redirect_response
    assert isinstance(redirected_request, TransportPolicyRequest)
    assert redirected_request == TransportPolicyRequest(GET, final_url, "empty", 1, expected_extensions)
    assert isinstance(final_response, TransportPolicyResponse)
    assert final_response.request == redirected_request
    assert final_response.status_code == OK
    assert response.request.extensions is first_request.extensions
    assert all(item.request.extensions is first_request.extensions for item in response.history)


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


async def test_async_policy_hooks_keep_extensions_isolated_under_overlap(http_server: str) -> None:
    urls = [f"{http_server}/status/{OK}?request={index}" for index in range(2)]
    request_ids = {url: index for index, url in enumerate(urls)}
    overlap = Barrier(len(urls))
    observed: dict[str, object] = {}

    def observe(request: TransportPolicyRequest) -> None:
        overlap.wait(timeout=5.0)
        observed[request.url] = request.extensions["tests.request_id"]

    hooks = TransportPolicyHooks(before_send=observe)

    async with foghttp.AsyncClient(
        policy_hooks=hooks,
        runtime="dedicated",
        runtime_workers=2,
    ) as client:
        responses = await asyncio.gather(
            *(client.get(url, extensions={"tests.request_id": request_ids[url]}) for url in urls),
        )

    assert all(response.status_code == OK for response in responses)
    assert observed == request_ids


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
