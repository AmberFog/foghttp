from collections.abc import AsyncIterator
from dataclasses import FrozenInstanceError

import pytest

import foghttp
from foghttp.policy import (
    TransportPolicyBodyState,
    TransportPolicyHooks,
    TransportPolicyRequest,
    TransportPolicyResponse,
)


def test_empty_policy_hooks_are_disabled() -> None:
    assert TransportPolicyHooks().enabled is False


def test_configured_policy_hook_is_enabled() -> None:
    def observe(request: TransportPolicyRequest) -> None:
        del request

    hooks = TransportPolicyHooks(before_send=observe)

    assert hooks.enabled is True


def test_policy_hook_config_repr_omits_callbacks() -> None:
    def observe(request: TransportPolicyRequest) -> None:
        del request

    assert "observe" not in repr(TransportPolicyHooks(before_send=observe))


@pytest.mark.parametrize(
    "field",
    ["before_send", "on_response_headers", "after_response_body"],
)
def test_policy_hooks_reject_non_callable_values(field: str) -> None:
    with pytest.raises(TypeError, match=rf"{field} .* must be callable or None"):
        TransportPolicyHooks(**{field: object()})


def test_policy_hooks_reject_coroutine_functions() -> None:
    async def async_hook(request: TransportPolicyRequest) -> None:
        del request

    with pytest.raises(TypeError, match=r"before_send .* must be synchronous"):
        TransportPolicyHooks(before_send=async_hook)


def test_policy_hooks_reject_async_callable_objects() -> None:
    class AsyncPolicyHook:
        async def __call__(self, request: TransportPolicyRequest) -> None:
            del request

    with pytest.raises(TypeError, match=r"before_send .* must be synchronous"):
        TransportPolicyHooks(before_send=AsyncPolicyHook())


def test_policy_hooks_reject_async_generator_functions() -> None:
    async def async_hook(request: TransportPolicyRequest) -> AsyncIterator[None]:
        del request
        yield

    with pytest.raises(TypeError, match=r"before_send .* must be synchronous"):
        TransportPolicyHooks(before_send=async_hook)


def test_policy_views_are_immutable_snapshots() -> None:
    request = TransportPolicyRequest(
        method="GET",
        url="https://example.com/resource",
        body="empty",
        redirect_hop=0,
    )
    response = TransportPolicyResponse(
        request=request,
        status_code=200,
        headers=(("content-type", "application/json"),),
    )

    with pytest.raises(FrozenInstanceError):
        request.method = "POST"
    with pytest.raises(FrozenInstanceError):
        response.status_code = 201

    assert isinstance(response.headers, tuple)
    assert isinstance(response.headers[0], tuple)


def test_policy_view_repr_redacts_url_and_header_values() -> None:
    extension_key = "tests.private"
    extension_value = "private-extension-value"
    request = TransportPolicyRequest(
        method="GET",
        url="https://example.com/resource?access_token=secret",
        body="empty",
        redirect_hop=0,
        extensions=foghttp.RequestExtensions({extension_key: extension_value}),
    )
    response = TransportPolicyResponse(
        request=request,
        status_code=200,
        headers=(("set-cookie", "session=secret"),),
    )

    representation = repr(response)

    assert "access_token=<redacted>" in representation
    assert "session=secret" not in representation
    assert extension_key not in representation
    assert extension_value not in representation
    assert "headers=<1 headers>" in representation
    assert "extensions=<1 items>" in representation


def test_policy_contracts_are_exported_at_package_root() -> None:
    assert foghttp.TransportPolicyBodyState is TransportPolicyBodyState
    assert foghttp.TransportPolicyHooks is TransportPolicyHooks
    assert foghttp.TransportPolicyRequest is TransportPolicyRequest
    assert foghttp.TransportPolicyResponse is TransportPolicyResponse
