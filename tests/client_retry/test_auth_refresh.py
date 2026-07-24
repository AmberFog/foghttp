import pytest

import foghttp
from foghttp.auth import AuthRequest
from foghttp.status_codes.success import OK

from .constants import CLOSE_THEN_OK_PATH, STATUS_THEN_OK_PATH
from .server import RetryTestServer


EXPECTED_AUTH_CALLS = 2
SECOND_AUTH_REFRESH_FAILURE = "second auth refresh failed"


def test_sync_callable_auth_refreshes_for_status_retry(retry_server: RetryTestServer) -> None:
    calls: list[AuthRequest] = []

    def authenticate(request: AuthRequest) -> dict[str, str]:
        calls.append(request)
        return {"Authorization": f"Bearer attempt-{len(calls)}"}

    with foghttp.Client(
        auth=authenticate,
        retry=foghttp.RetryPolicy(retries=1, backoff=0, jitter=0),
    ) as client:
        response = client.get(retry_server.url + STATUS_THEN_OK_PATH)

    requests = retry_server.snapshot().requests_for(STATUS_THEN_OK_PATH)
    assert response.status_code == OK
    assert [request.authorization for request in requests] == [
        "Bearer attempt-1",
        "Bearer attempt-2",
    ]
    assert [request.redirect_hop for request in calls] == [0, 0]


async def test_async_callable_auth_refreshes_for_status_retry(
    retry_server: RetryTestServer,
) -> None:
    calls: list[AuthRequest] = []

    def authenticate(request: AuthRequest) -> dict[str, str]:
        calls.append(request)
        return {"Authorization": f"Bearer attempt-{len(calls)}"}

    async with foghttp.AsyncClient(
        auth=authenticate,
        retry=foghttp.RetryPolicy(retries=1, backoff=0, jitter=0),
    ) as client:
        response = await client.get(retry_server.url + STATUS_THEN_OK_PATH)

    requests = retry_server.snapshot().requests_for(STATUS_THEN_OK_PATH)
    assert response.status_code == OK
    assert [request.authorization for request in requests] == [
        "Bearer attempt-1",
        "Bearer attempt-2",
    ]
    assert [request.redirect_hop for request in calls] == [0, 0]


def test_sync_callable_auth_refreshes_for_network_retry(
    retry_server: RetryTestServer,
) -> None:
    calls: list[AuthRequest] = []

    def authenticate(request: AuthRequest) -> dict[str, str]:
        calls.append(request)
        return {"Authorization": f"Bearer attempt-{len(calls)}"}

    with foghttp.Client(
        auth=authenticate,
        retry=foghttp.RetryPolicy(retries=1, backoff=0, jitter=0),
    ) as client:
        response = client.get(retry_server.url + CLOSE_THEN_OK_PATH)

    requests = retry_server.snapshot().requests_for(CLOSE_THEN_OK_PATH)
    assert response.status_code == OK
    assert [request.authorization for request in requests] == [
        "Bearer attempt-1",
        "Bearer attempt-2",
    ]
    assert [request.redirect_hop for request in calls] == [0, 0]


async def test_async_callable_auth_restores_client_default_before_retry_refresh(
    retry_server: RetryTestServer,
) -> None:
    default_authorization = "Bearer client-default"
    observed_authorization: list[str] = []

    def authenticate(request: AuthRequest) -> dict[str, str] | None:
        observed_authorization.append(foghttp.Headers(request.headers)["authorization"])
        if len(observed_authorization) == 1:
            return {"Authorization": "Bearer first-attempt"}
        return None

    async with foghttp.AsyncClient(
        headers={"Authorization": default_authorization},
        auth=authenticate,
        retry=foghttp.RetryPolicy(retries=1, backoff=0, jitter=0),
    ) as client:
        response = await client.get(retry_server.url + STATUS_THEN_OK_PATH)

    requests = retry_server.snapshot().requests_for(STATUS_THEN_OK_PATH)
    assert response.status_code == OK
    assert observed_authorization == [default_authorization, default_authorization]
    assert [request.authorization for request in requests] == [
        "Bearer first-attempt",
        default_authorization,
    ]


def test_auth_refresh_failure_before_retry_releases_resources(
    retry_server: RetryTestServer,
) -> None:
    calls = 0

    def authenticate(_request: AuthRequest) -> dict[str, str]:
        nonlocal calls
        calls += 1
        if calls == EXPECTED_AUTH_CALLS:
            raise RuntimeError(SECOND_AUTH_REFRESH_FAILURE)
        return {"Authorization": "Bearer initial"}

    with foghttp.Client(
        auth=authenticate,
        retry=foghttp.RetryPolicy(retries=1, backoff=0, jitter=0),
    ) as client:
        with pytest.raises(RuntimeError, match="second auth refresh failed"):
            client.get(retry_server.url + STATUS_THEN_OK_PATH)
        stats = client.stats()

    requests = retry_server.snapshot().requests_for(STATUS_THEN_OK_PATH)
    assert len(requests) == 1
    assert calls == EXPECTED_AUTH_CALLS
    assert stats.active_requests == 0
    assert stats.pending_requests == 0
