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


async def test_async_invalid_url_is_rejected_before_transport() -> None:
    async with foghttp.AsyncClient(timeouts=NETWORK_ERROR_TIMEOUTS) as client:
        with pytest.raises(ValueError, match="URL is invalid"):
            await client.get(INVALID_URL)

        stats = client.stats()

    assert_invalid_url_does_not_touch_transport(stats)


async def test_async_connection_refused_maps_to_network_error_and_client_recovers(
    async_connection_refused_url: str,
    http_server: str,
) -> None:
    async with foghttp.AsyncClient(timeouts=NETWORK_ERROR_TIMEOUTS) as client:
        with pytest.raises(foghttp.NetworkError) as exc_info:
            await client.get(async_connection_refused_url)

        stats_after_error = client.stats()
        response = await client.get(http_server)
        final_stats = client.stats()

    assert not isinstance(exc_info.value, foghttp.TimeoutError)
    assert_connection_open_failed_stats(stats_after_error)
    assert response.status_code == OK
    assert_recovered_stats(final_stats)


async def test_async_malformed_response_maps_to_network_error_and_client_recovers(
    broken_http_server: str,
    http_server: str,
) -> None:
    async with foghttp.AsyncClient(timeouts=NETWORK_ERROR_TIMEOUTS) as client:
        with pytest.raises(foghttp.NetworkError) as exc_info:
            await client.get(f"{broken_http_server}{MALFORMED_RESPONSE_PATH}")

        stats_after_error = client.stats()
        response = await client.get(http_server)
        final_stats = client.stats()

    assert not isinstance(exc_info.value, foghttp.TimeoutError)
    assert_network_error_stats(stats_after_error)
    assert response.status_code == OK
    assert_recovered_stats(final_stats)


async def test_async_mid_response_close_maps_to_request_error_and_client_recovers(
    broken_http_server: str,
    http_server: str,
) -> None:
    async with foghttp.AsyncClient(timeouts=NETWORK_ERROR_TIMEOUTS) as client:
        with pytest.raises(foghttp.RequestError) as exc_info:
            await client.get(f"{broken_http_server}{MID_RESPONSE_CLOSE_PATH}")

        stats_after_error = client.stats()
        response = await client.get(http_server)
        final_stats = client.stats()

    assert not isinstance(exc_info.value, foghttp.TimeoutError)
    assert not isinstance(exc_info.value, foghttp.NetworkError)
    assert_network_error_stats(stats_after_error)
    assert response.status_code == OK
    assert_recovered_stats(final_stats)
