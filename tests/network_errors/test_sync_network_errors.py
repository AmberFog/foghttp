import pytest

import foghttp
from foghttp.status_codes.success import OK

from .constants import (
    INVALID_URL,
    MALFORMED_RESPONSE_PATH,
    MID_RESPONSE_CLOSE_PATH,
    NETWORK_ERROR_TIMEOUTS,
)
from .helpers import (
    assert_connection_open_failed_stats,
    assert_invalid_url_does_not_touch_transport,
    assert_network_error_stats,
    assert_recovered_stats,
)


def test_sync_invalid_url_is_rejected_before_transport() -> None:
    with foghttp.Client(timeouts=NETWORK_ERROR_TIMEOUTS) as client:
        with pytest.raises(ValueError, match="URL is invalid"):
            client.get(INVALID_URL)

        stats = client.stats()

    assert_invalid_url_does_not_touch_transport(stats)


def test_sync_connection_refused_maps_to_request_error_and_client_recovers(
    connection_refused_url: str,
    sync_http_server: str,
) -> None:
    with foghttp.Client(timeouts=NETWORK_ERROR_TIMEOUTS) as client:
        with pytest.raises(foghttp.RequestError) as exc_info:
            client.get(connection_refused_url)

        stats_after_error = client.stats()
        response = client.get(sync_http_server)
        final_stats = client.stats()

    assert not isinstance(exc_info.value, foghttp.TimeoutError)
    assert_connection_open_failed_stats(stats_after_error)
    assert response.status_code == OK
    assert_recovered_stats(final_stats)


def test_sync_malformed_response_maps_to_request_error_and_client_recovers(
    broken_http_server: str,
    sync_http_server: str,
) -> None:
    with foghttp.Client(timeouts=NETWORK_ERROR_TIMEOUTS) as client:
        with pytest.raises(foghttp.RequestError) as exc_info:
            client.get(f"{broken_http_server}{MALFORMED_RESPONSE_PATH}")

        stats_after_error = client.stats()
        response = client.get(sync_http_server)
        final_stats = client.stats()

    assert not isinstance(exc_info.value, foghttp.TimeoutError)
    assert_network_error_stats(stats_after_error)
    assert response.status_code == OK
    assert_recovered_stats(final_stats)


def test_sync_mid_response_close_maps_to_request_error_and_client_recovers(
    broken_http_server: str,
    sync_http_server: str,
) -> None:
    with foghttp.Client(timeouts=NETWORK_ERROR_TIMEOUTS) as client:
        with pytest.raises(foghttp.RequestError) as exc_info:
            client.get(f"{broken_http_server}{MID_RESPONSE_CLOSE_PATH}")

        stats_after_error = client.stats()
        response = client.get(sync_http_server)
        final_stats = client.stats()

    assert not isinstance(exc_info.value, foghttp.TimeoutError)
    assert_network_error_stats(stats_after_error)
    assert response.status_code == OK
    assert_recovered_stats(final_stats)
