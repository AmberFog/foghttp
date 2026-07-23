from collections.abc import Callable
from typing import assert_type

import foghttp
from foghttp.policy import (
    TransportPolicyHooks,
    TransportPolicyRequest,
    TransportPolicyResponse,
)


def observe_request(request: TransportPolicyRequest) -> None:
    assert request.method
    assert_type(request.extensions, foghttp.RequestExtensions)


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


async def test_retry_policy_contracts() -> None:
    conditions = foghttp.RetryConditions(
        statuses=(429, 503),
        exceptions=(foghttp.NetworkError,),
    )
    policy = foghttp.RetryPolicy(
        retries=3,
        backoff=0.25,
        jitter=0.05,
        retry_on=conditions,
        methods=("GET", "QUERY"),
    )

    assert_type(policy.retries, int)
    assert_type(policy.backoff, float)
    assert_type(policy.jitter, float)
    assert_type(policy.retry_on, foghttp.RetryConditions)
    assert_type(policy.methods, frozenset[str])
    assert_type(conditions.statuses, frozenset[int])
    assert_type(conditions.exceptions, tuple[type[foghttp.NetworkError], ...])

    sync_client = foghttp.Client(retry=policy)
    async_client = foghttp.AsyncClient(retry=policy)
    sync_client.close()
    assert_type(async_client, foghttp.AsyncClient)
    await async_client.aclose()


async def test_ssrf_policy_contracts() -> None:
    policy = foghttp.SSRFPolicy(
        allowed_schemes=("https",),
        allowed_origins=("https://api.example.com",),
        allowed_domains=("example.org",),
    )

    assert_type(policy.allowed_schemes, frozenset[str])
    assert_type(policy.allowed_origins, frozenset[str])
    assert_type(policy.allowed_domains, frozenset[str])
    error = foghttp.SSRFError(
        "destination blocked",
        reason=foghttp.SSRFViolationReason.NON_PUBLIC_ADDRESS,
    )
    assert_type(error.reason, foghttp.SSRFViolationReason)

    sync_client = foghttp.Client(ssrf=policy)
    async_client = foghttp.AsyncClient(ssrf=policy)
    sync_client.close()
    assert_type(async_client, foghttp.AsyncClient)
    await async_client.aclose()
