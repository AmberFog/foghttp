import asyncio

import pytest

import foghttp
from foghttp.status_codes.success import OK
from tests.support.timeout_diagnostics import assert_timeout_diagnostic
from tests.support.transport_stats import wait_for_async_transport_stats

from .assertions import (
    assert_recovered_after_tls_failure,
    assert_tls_failure_stats,
    assert_tls_handshake_timeout_stats,
)
from .certificates import TLSCertificateBundle
from .constants import TLS_OK_BODY, TLS_PATH
from .handshake_server import TLSHandshakeStallServer
from .models import TLSServer


TLS_HANDSHAKE_TIMEOUTS = foghttp.Timeouts(total=0.2)
TLS_RECOVERY_TIMEOUTS = foghttp.Timeouts(total=1.0)


async def test_async_client_accepts_custom_ca_certificate(
    tls_certificates: TLSCertificateBundle,
    tls_http_server: TLSServer,
) -> None:
    tls = foghttp.TLSConfig(ca_certificates=(tls_certificates.ca_path,))

    async with foghttp.AsyncClient(tls=tls) as client:
        response = await client.get(tls_http_server.url + TLS_PATH)

    assert response.status_code == OK
    assert response.content == TLS_OK_BODY


async def test_async_client_accepts_custom_only_ca_trust(
    tls_certificates: TLSCertificateBundle,
    tls_http_server: TLSServer,
) -> None:
    tls = foghttp.TLSConfig(
        ca_certificates=(tls_certificates.ca_path,),
        trust_webpki_roots=False,
    )

    async with foghttp.AsyncClient(tls=tls) as client:
        response = await client.get(tls_http_server.url + TLS_PATH)

    assert response.status_code == OK
    assert response.content == TLS_OK_BODY


async def test_async_client_rejects_untrusted_tls_certificate_and_recovers(
    tls_http_server: TLSServer,
    http_server: str,
) -> None:
    async with foghttp.AsyncClient() as client:
        with pytest.raises(foghttp.NetworkError):
            await client.get(tls_http_server.url + TLS_PATH)

        stats_after_failure = client.stats()
        recovery_response = await client.get(http_server)
        final_stats = client.stats()

    assert_tls_failure_stats(stats_after_failure)
    assert recovery_response.status_code == OK
    assert_recovered_after_tls_failure(final_stats)


async def test_async_tls_handshake_timeout_releases_transport_state_and_recovers(
    tls_handshake_stall_server: TLSHandshakeStallServer,
    http_server: str,
) -> None:
    async with foghttp.AsyncClient(timeouts=TLS_HANDSHAKE_TIMEOUTS) as client:
        with pytest.raises(foghttp.TimeoutError, match="request total timeout expired") as exc_info:
            await client.get(tls_handshake_stall_server.url + TLS_PATH)

        await asyncio.to_thread(tls_handshake_stall_server.wait_for_connections, 1)
        await wait_for_async_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.pending_requests == 0,
            message="TLS handshake timeout did not release request slots",
        )
        stats_after_timeout = client.stats()
        recovery_response = await client.get(http_server, timeout=TLS_RECOVERY_TIMEOUTS)
        final_stats = client.stats()

    assert_timeout_diagnostic(
        exc_info.value,
        phase="response_headers",
        origin=tls_handshake_stall_server.url,
        timeout=TLS_HANDSHAKE_TIMEOUTS.total,
    )
    assert_tls_handshake_timeout_stats(stats_after_timeout)
    assert recovery_response.status_code == OK
    assert_recovered_after_tls_failure(final_stats)
