import pytest

import foghttp
from foghttp.status_codes.success import OK
from tests.http_body_scenarios import (
    INCOMPLETE_CHUNKED_BODY_PATH,
    SLOW_BODY_PATH,
    TOO_LARGE_SIZE_HINT_PATH,
)

from .constants import (
    BODY_BELOW_LIMIT_SIZE,
    BODY_LIMIT,
    BODY_TOO_LARGE_SIZE,
    EMPTY_BODY_SIZE,
    EXPECTED_TOTAL_REQUESTS_AFTER_RETRY,
    UNKNOWN_SIZE_BYTES_PATH,
)


@pytest.mark.parametrize(
    ("body_size", "body_limit"),
    (
        (EMPTY_BODY_SIZE, EMPTY_BODY_SIZE),
        (BODY_BELOW_LIMIT_SIZE, BODY_LIMIT),
        (BODY_LIMIT, BODY_LIMIT),
    ),
)
def test_sync_buffered_response_body_within_limit(
    sync_http_server: str,
    body_size: int,
    body_limit: int,
) -> None:
    limits = foghttp.Limits(max_response_body_size=body_limit)

    with foghttp.Client(limits=limits) as client:
        response = client.get(f"{sync_http_server}/bytes/{body_size}")
        stats = client.stats()

    assert response.status_code == OK
    assert response.content == b"x" * body_size
    assert stats.total_requests == 1
    assert stats.failed_requests == 0
    assert stats.active_requests == 0
    assert stats.pending_requests == 0


def test_sync_buffered_response_body_limit_error_releases_request_slot(
    sync_http_server: str,
) -> None:
    limits = foghttp.Limits(max_response_body_size=BODY_LIMIT)

    with foghttp.Client(limits=limits) as client:
        with pytest.raises(
            foghttp.ResponseBodyTooLargeError,
            match="response body exceeded max_response_body_size",
        ):
            client.get(f"{sync_http_server}/bytes/{BODY_TOO_LARGE_SIZE}")

        stats_after_error = client.stats()
        retry_response = client.get(f"{sync_http_server}/bytes/{BODY_LIMIT}")
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


def test_sync_default_response_body_limit_rejects_large_size_hint(
    sync_http_server: str,
) -> None:
    with foghttp.Client() as client:
        with pytest.raises(
            foghttp.ResponseBodyTooLargeError,
            match="response body exceeded max_response_body_size",
        ):
            client.get(f"{sync_http_server}{TOO_LARGE_SIZE_HINT_PATH}")

        stats_after_error = client.stats()

    assert stats_after_error.total_requests == 1
    assert stats_after_error.failed_requests == 1
    assert stats_after_error.active_requests == 0
    assert stats_after_error.pending_requests == 0


def test_sync_total_timeout_applies_to_slow_response_body(
    sync_http_server: str,
) -> None:
    timeouts = foghttp.Timeouts(total=0.05)

    with foghttp.Client(timeouts=timeouts) as client:
        with pytest.raises(foghttp.TimeoutError, match="request total timeout expired"):
            client.get(f"{sync_http_server}{SLOW_BODY_PATH}")

        stats_after_error = client.stats()

    assert stats_after_error.total_requests == 1
    assert stats_after_error.failed_requests == 1
    assert stats_after_error.active_requests == 0
    assert stats_after_error.pending_requests == 0


def test_sync_total_timeout_applies_to_incomplete_chunked_response_body(
    sync_http_server: str,
) -> None:
    timeouts = foghttp.Timeouts(total=0.05)

    with foghttp.Client(timeouts=timeouts) as client:
        with pytest.raises(foghttp.TimeoutError, match="request total timeout expired"):
            client.get(f"{sync_http_server}{INCOMPLETE_CHUNKED_BODY_PATH}")

        stats_after_error = client.stats()

    assert stats_after_error.total_requests == 1
    assert stats_after_error.failed_requests == 1
    assert stats_after_error.active_requests == 0
    assert stats_after_error.pending_requests == 0


def test_sync_buffered_response_body_limit_error_without_known_size_releases_request_slot(
    sync_http_server: str,
) -> None:
    limits = foghttp.Limits(max_response_body_size=BODY_LIMIT)

    with foghttp.Client(limits=limits) as client:
        with pytest.raises(
            foghttp.ResponseBodyTooLargeError,
            match="response body exceeded max_response_body_size",
        ):
            client.get(f"{sync_http_server}{UNKNOWN_SIZE_BYTES_PATH}/{BODY_TOO_LARGE_SIZE}")

        stats_after_error = client.stats()

    assert stats_after_error.total_requests == 1
    assert stats_after_error.failed_requests == 1
    assert stats_after_error.active_requests == 0
    assert stats_after_error.pending_requests == 0
