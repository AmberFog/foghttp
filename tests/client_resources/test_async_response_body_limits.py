import asyncio

import pytest

import foghttp
from foghttp.status_codes.success import OK
from tests.client_timeouts.helpers import assert_timeout_diagnostic
from tests.http_body_scenarios import (
    DELAYED_EOF_UNKNOWN_SIZE_BYTES_PATH,
    INCOMPLETE_CHUNKED_BODY_PATH,
    SLOW_BODY_PATH,
    TOO_LARGE_SIZE_HINT_PATH,
)

from .constants import (
    BODY_BELOW_LIMIT_SIZE,
    BODY_LIMIT,
    BODY_TOO_LARGE_SIZE,
    CONCURRENT_RESPONSE_COUNT,
    EMPTY_BODY_SIZE,
    EXPECTED_BODY_BUDGET_REJECTIONS,
    EXPECTED_TOTAL_REQUESTS_AFTER_RETRY,
    INVALID_BODY_SIZE_SEGMENT,
    NEGATIVE_BODY_SIZE_SEGMENT,
    UNKNOWN_SIZE_BYTES_PATH,
)


@pytest.mark.parametrize(
    ("body_size", "body_limit"),
    (
        pytest.param(EMPTY_BODY_SIZE, EMPTY_BODY_SIZE, id="empty-body"),
        pytest.param(BODY_BELOW_LIMIT_SIZE, BODY_LIMIT, id="below-limit"),
        pytest.param(BODY_LIMIT, BODY_LIMIT, id="at-limit"),
    ),
)
async def test_async_buffered_response_body_within_limit(
    http_server: str,
    body_size: int,
    body_limit: int,
) -> None:
    limits = foghttp.Limits(max_response_body_size=body_limit)

    async with foghttp.AsyncClient(limits=limits) as client:
        response = await client.get(f"{http_server}/bytes/{body_size}")
        stats = client.stats()

    assert response.status_code == OK
    assert response.content == b"x" * body_size
    assert stats.total_requests == 1
    assert stats.failed_requests == 0
    assert stats.active_requests == 0
    assert stats.pending_requests == 0


async def test_async_buffered_response_body_limit_error_releases_request_slot(
    http_server: str,
) -> None:
    limits = foghttp.Limits(max_response_body_size=BODY_LIMIT)

    async with foghttp.AsyncClient(limits=limits) as client:
        with pytest.raises(
            foghttp.ResponseBodyTooLargeError,
            match="response body exceeded max_response_body_size",
        ):
            await client.get(f"{http_server}/bytes/{BODY_TOO_LARGE_SIZE}")

        stats_after_error = client.stats()
        retry_response = await client.get(f"{http_server}/bytes/{BODY_LIMIT}")
        final_stats = client.stats()

    assert stats_after_error.total_requests == 1
    assert stats_after_error.failed_requests == 1
    assert stats_after_error.active_requests == 0
    assert stats_after_error.pending_requests == 0
    assert retry_response.status_code == OK
    assert retry_response.content == b"x" * BODY_LIMIT
    assert final_stats.total_requests == EXPECTED_TOTAL_REQUESTS_AFTER_RETRY
    assert final_stats.failed_requests == 1
    assert final_stats.active_requests == 0
    assert final_stats.pending_requests == 0


async def test_async_default_response_body_limit_rejects_large_size_hint(
    http_server: str,
) -> None:
    async with foghttp.AsyncClient() as client:
        with pytest.raises(
            foghttp.ResponseBodyTooLargeError,
            match="response body exceeded max_response_body_size",
        ):
            await client.get(f"{http_server}{TOO_LARGE_SIZE_HINT_PATH}")

        stats_after_error = client.stats()

    assert stats_after_error.total_requests == 1
    assert stats_after_error.failed_requests == 1
    assert stats_after_error.active_requests == 0
    assert stats_after_error.pending_requests == 0


async def test_async_total_timeout_applies_to_slow_response_body(
    http_server: str,
) -> None:
    timeouts = foghttp.Timeouts(total=0.05)

    async with foghttp.AsyncClient(timeouts=timeouts) as client:
        with pytest.raises(foghttp.TimeoutError, match="request total timeout expired") as exc_info:
            await client.get(f"{http_server}{SLOW_BODY_PATH}")

        stats_after_error = client.stats()

    assert_timeout_diagnostic(
        exc_info.value,
        phase="response_body",
        origin=http_server,
        timeout=timeouts.total,
    )
    assert stats_after_error.total_requests == 1
    assert stats_after_error.failed_requests == 1
    assert stats_after_error.active_requests == 0
    assert stats_after_error.pending_requests == 0


async def test_async_total_timeout_applies_to_incomplete_chunked_response_body(
    http_server: str,
) -> None:
    timeouts = foghttp.Timeouts(total=0.05)

    async with foghttp.AsyncClient(timeouts=timeouts) as client:
        with pytest.raises(foghttp.TimeoutError, match="request total timeout expired") as exc_info:
            await client.get(f"{http_server}{INCOMPLETE_CHUNKED_BODY_PATH}")

        stats_after_error = client.stats()

    assert_timeout_diagnostic(
        exc_info.value,
        phase="response_body",
        origin=http_server,
        timeout=timeouts.total,
    )
    assert stats_after_error.total_requests == 1
    assert stats_after_error.failed_requests == 1
    assert stats_after_error.active_requests == 0
    assert stats_after_error.pending_requests == 0


async def test_async_buffered_response_body_limit_error_without_known_size_releases_request_slot(
    http_server: str,
) -> None:
    limits = foghttp.Limits(max_response_body_size=BODY_LIMIT)

    async with foghttp.AsyncClient(limits=limits) as client:
        with pytest.raises(
            foghttp.ResponseBodyTooLargeError,
            match="response body exceeded max_response_body_size",
        ):
            await client.get(f"{http_server}{UNKNOWN_SIZE_BYTES_PATH}/{BODY_TOO_LARGE_SIZE}")

        stats_after_error = client.stats()

    assert stats_after_error.total_requests == 1
    assert stats_after_error.failed_requests == 1
    assert stats_after_error.active_requests == 0
    assert stats_after_error.pending_requests == 0


@pytest.mark.parametrize(
    "size_segment",
    (
        pytest.param(INVALID_BODY_SIZE_SEGMENT, id="not-an-int-size"),
        pytest.param(NEGATIVE_BODY_SIZE_SEGMENT, id="negative-size"),
    ),
)
async def test_async_invalid_delayed_eof_size_falls_through_without_crashing_server(
    http_server: str,
    size_segment: str,
) -> None:
    url = f"{http_server}{DELAYED_EOF_UNKNOWN_SIZE_BYTES_PATH}/{size_segment}"
    expected_request_line = f"GET {DELAYED_EOF_UNKNOWN_SIZE_BYTES_PATH}/{size_segment} HTTP/1.1"

    async with foghttp.AsyncClient() as client:
        response = await client.get(url)
        stats = client.stats()

    assert response.status_code == OK
    assert response.json()["request_line"] == expected_request_line
    assert stats.total_requests == 1
    assert stats.failed_requests == 0
    assert stats.active_requests == 0
    assert stats.pending_requests == 0


async def test_async_aggregate_buffered_response_budget_limits_concurrent_bodies(
    http_server: str,
) -> None:
    limits = foghttp.Limits(
        max_response_body_size=BODY_LIMIT,
        max_buffered_response_bytes=BODY_LIMIT,
    )
    url = f"{http_server}{DELAYED_EOF_UNKNOWN_SIZE_BYTES_PATH}/{BODY_LIMIT}"

    async with foghttp.AsyncClient(limits=limits) as client:
        results = await asyncio.gather(
            *(client.get(url) for _ in range(CONCURRENT_RESPONSE_COUNT)),
            return_exceptions=True,
        )
        stats = client.stats()

    responses = [result for result in results if isinstance(result, foghttp.Response)]
    errors = [result for result in results if isinstance(result, foghttp.ResponseBodyBudgetExceededError)]
    unexpected_results = [
        result
        for result in results
        if not isinstance(result, (foghttp.Response, foghttp.ResponseBodyBudgetExceededError))
    ]

    assert unexpected_results == []
    assert len(responses) == 1
    assert responses[0].status_code == OK
    assert responses[0].content == b"x" * BODY_LIMIT
    assert len(errors) == EXPECTED_BODY_BUDGET_REJECTIONS
    assert stats.total_requests == CONCURRENT_RESPONSE_COUNT
    assert stats.failed_requests == EXPECTED_BODY_BUDGET_REJECTIONS
    assert stats.active_requests == 0
    assert stats.pending_requests == 0
    assert stats.buffered_response_bytes == 0
    assert stats.buffered_response_budget_rejections == EXPECTED_BODY_BUDGET_REJECTIONS


async def test_async_aggregate_buffered_response_budget_releases_between_sequential_bodies(
    http_server: str,
) -> None:
    limits = foghttp.Limits(
        max_response_body_size=BODY_LIMIT,
        max_buffered_response_bytes=BODY_LIMIT,
    )
    url = f"{http_server}/bytes/{BODY_LIMIT}"

    async with foghttp.AsyncClient(limits=limits) as client:
        first_response = await client.get(url)
        stats_after_first_response = client.stats()
        second_response = await client.get(url)
        stats = client.stats()

    assert first_response.status_code == OK
    assert first_response.content == b"x" * BODY_LIMIT
    assert stats_after_first_response.total_requests == 1
    assert stats_after_first_response.buffered_response_bytes == 0
    assert second_response.status_code == OK
    assert second_response.content == b"x" * BODY_LIMIT
    assert stats.total_requests == EXPECTED_TOTAL_REQUESTS_AFTER_RETRY
    assert stats.failed_requests == 0
    assert stats.active_requests == 0
    assert stats.pending_requests == 0
    assert stats.buffered_response_bytes == 0
    assert stats.buffered_response_budget_rejections == 0
