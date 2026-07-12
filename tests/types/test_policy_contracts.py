from collections.abc import Callable
from typing import assert_type

from foghttp import RequestExtensions
from foghttp.policy import (
    TransportPolicyHooks,
    TransportPolicyRequest,
    TransportPolicyResponse,
)


def observe_request(request: TransportPolicyRequest) -> None:
    assert request.method
    assert_type(request.extensions, RequestExtensions)


def observe_response(response: TransportPolicyResponse) -> None:
    assert response.status_code > 0


def test_policy_hook_callable_contracts() -> None:
    hooks = TransportPolicyHooks(
        before_send=observe_request,
        on_response_headers=observe_response,
        after_response_body=observe_response,
    )

    assert_type(
        hooks.before_send,
        Callable[[TransportPolicyRequest], None] | None,
    )
    assert_type(
        hooks.on_response_headers,
        Callable[[TransportPolicyResponse], None] | None,
    )
    assert_type(
        hooks.after_response_body,
        Callable[[TransportPolicyResponse], None] | None,
    )
    assert hooks.enabled is True
