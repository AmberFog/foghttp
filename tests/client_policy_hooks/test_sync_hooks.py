from typing import cast

import pytest

import foghttp
from foghttp.methods import GET
from foghttp.policy import (
    TransportPolicyHooks,
    TransportPolicyRequest,
    TransportPolicyResponse,
)
from foghttp.status_codes.redirect import FOUND, SEE_OTHER, TEMPORARY_REDIRECT
from foghttp.status_codes.success import OK
from tests.client_policy_hooks.requests import send_sync_request
from tests.support.http_routes import REPEATED_HEADERS_PATH


@pytest.mark.parametrize("streaming", [False, True], ids=("buffered", "streaming"))
def test_sync_policy_hooks_observe_each_transport_stage(
    sync_http_server: str,
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
    initial_url = f"{sync_http_server}/redirect/{FOUND}"
    extensions = {"tests.request_id": initial_url}
    expected_extensions = foghttp.RequestExtensions(extensions)

    with foghttp.Client(follow_redirects=True, policy_hooks=hooks) as client:
        if streaming:
            with client.stream(GET, initial_url, extensions=extensions) as response:
                assert response.status_code == OK
                final_url = response.url
        else:
            response = client.get(initial_url, extensions=extensions)
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
    assert redirect_response.request is not first_request
    assert redirect_response.request == first_request
    assert redirect_response.status_code == FOUND
    assert ("location", "/final") in redirect_response.headers
    assert events[2][1] == redirect_response
    assert isinstance(redirected_request, TransportPolicyRequest)
    assert redirected_request == TransportPolicyRequest(GET, final_url, "empty", 1, expected_extensions)
    assert isinstance(final_response, TransportPolicyResponse)
    assert final_response.request == redirected_request
    assert final_response.status_code == OK
    assert response.request.extensions is first_request.extensions
    assert all(item.request.extensions is first_request.extensions for item in response.history)


def test_sync_hook_exception_is_propagated_before_transport_acquire(sync_http_server: str) -> None:
    def reject_request(request: TransportPolicyRequest) -> None:
        message = f"blocked {request.method}"
        raise RuntimeError(message)

    hooks = TransportPolicyHooks(before_send=reject_request)

    with foghttp.Client(policy_hooks=hooks) as client:
        with pytest.raises(RuntimeError, match="blocked GET"):
            client.get(sync_http_server)
        stats = client.stats()

    assert stats.pool_acquire_attempts == 0


def test_request_hook_observes_body_policy_after_redirect_mutation(sync_http_server: str) -> None:
    requests: list[TransportPolicyRequest] = []
    hooks = TransportPolicyHooks(before_send=requests.append)

    with foghttp.Client(follow_redirects=True, policy_hooks=hooks) as client:
        response = client.post(
            f"{sync_http_server}/redirect/{SEE_OTHER}",
            content=b"payload",
        )

    assert response.status_code == OK
    assert [(request.method, request.body, request.redirect_hop) for request in requests] == [
        ("POST", "replayable", 0),
        ("GET", "empty", 1),
    ]


def test_response_hook_preserves_repeated_header_order(sync_http_server: str) -> None:
    observed: list[TransportPolicyResponse] = []
    hooks = TransportPolicyHooks(on_response_headers=observed.append)

    with foghttp.Client(policy_hooks=hooks) as client:
        client.get(sync_http_server + REPEATED_HEADERS_PATH)

    set_cookies = [value for name, value in observed[0].headers if name == "set-cookie"]
    assert set_cookies == ["first=1", "second=2"]


def test_policy_snapshot_escape_hatches_do_not_mutate_transport(sync_http_server: str) -> None:
    def mutate_request(request: TransportPolicyRequest) -> None:
        object.__setattr__(request, "method", "DELETE")
        object.__setattr__(request, "url", f"{sync_http_server}/status/500")

    def mutate_response(response: TransportPolicyResponse) -> None:
        object.__setattr__(response, "status_code", 500)
        object.__setattr__(response, "headers", (("x-mutated", "true"),))

    hooks = TransportPolicyHooks(
        before_send=mutate_request,
        on_response_headers=mutate_response,
    )

    with foghttp.Client(policy_hooks=hooks) as client:
        response = client.get(sync_http_server)

    assert response.status_code == OK
    assert response.json()["request_line"].startswith("GET / HTTP/")
    assert "x-mutated" not in response.headers


def test_sync_hook_return_value_is_rejected(sync_http_server: str) -> None:
    def invalid_hook(request: TransportPolicyRequest) -> None:
        return cast("None", request)

    hooks = TransportPolicyHooks(before_send=invalid_hook)

    with (
        foghttp.Client(policy_hooks=hooks) as client,
        pytest.raises(TypeError, match="transport policy hooks must return None"),
    ):
        client.get(sync_http_server)


@pytest.mark.parametrize("streaming", [False, True], ids=("buffered", "streaming"))
def test_sync_response_hook_failure_releases_transport_resources(
    sync_http_server: str,
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

    with foghttp.Client(policy_hooks=hooks, limits=limits) as client:
        with pytest.raises(RuntimeError, match="blocked status 200"):
            send_sync_request(client, sync_http_server, streaming=streaming)
        stats_after_error = client.stats()
        response = client.get(sync_http_server)

    assert response.status_code == OK
    assert stats_after_error.total_requests == 1
    assert stats_after_error.failed_requests == 1
    assert stats_after_error.active_requests == 0
    assert stats_after_error.pending_requests == 0
    assert stats_after_error.response_body_aborted == 1
    assert stats_after_error.connections_aborted == 1


@pytest.mark.parametrize("streaming", [False, True], ids=("buffered", "streaming"))
def test_after_body_hook_failure_releases_redirect_resources(
    sync_http_server: str,
    *,
    streaming: bool,
) -> None:
    def reject_redirect(response: TransportPolicyResponse) -> None:
        message = f"blocked redirect {response.status_code}"
        raise RuntimeError(message)

    hooks = TransportPolicyHooks(after_response_body=reject_redirect)
    limits = foghttp.Limits(max_active_requests=1, max_connections=1)
    redirect_url = f"{sync_http_server}/redirect/{FOUND}"

    with foghttp.Client(
        follow_redirects=True,
        policy_hooks=hooks,
        limits=limits,
    ) as client:
        with pytest.raises(RuntimeError, match=f"blocked redirect {FOUND}"):
            send_sync_request(client, redirect_url, streaming=streaming)
        stats_after_error = client.stats()
        response = client.get(sync_http_server)

    assert response.status_code == OK
    assert stats_after_error.total_requests == 1
    assert stats_after_error.failed_requests == 1
    assert stats_after_error.active_requests == 0
    assert stats_after_error.pending_requests == 0
    assert stats_after_error.buffered_response_bytes == 0
    assert stats_after_error.response_body_reuse_eligible + stats_after_error.response_body_closed == 1
    assert stats_after_error.response_body_aborted == 0
    assert stats_after_error.connections_aborted == 0


def test_redirect_safety_validation_precedes_after_body_hook(sync_http_server: str) -> None:
    observed: list[TransportPolicyResponse] = []
    hooks = TransportPolicyHooks(after_response_body=observed.append)

    with (
        foghttp.Client(follow_redirects=True, policy_hooks=hooks) as client,
        pytest.raises(foghttp.RequestError, match="non-replayable request body"),
    ):
        client.post(
            f"{sync_http_server}/redirect/{TEMPORARY_REDIRECT}",
            content=iter((b"payload",)),
        )

    assert observed == []
