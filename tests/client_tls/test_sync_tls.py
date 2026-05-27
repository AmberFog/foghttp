import pytest

import foghttp
from foghttp.status_codes.success import OK
from tests.support.timeout_diagnostics import assert_timeout_diagnostic
from tests.support.transport_stats import wait_for_sync_transport_stats

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


def test_sync_client_accepts_custom_ca_certificate(
    tls_certificates: TLSCertificateBundle,
    tls_http_server: TLSServer,
) -> None:
    tls = foghttp.TLSConfig(ca_certificates=(tls_certificates.ca_path,))

    with foghttp.Client(tls=tls) as client:
        response = client.get(tls_http_server.url + TLS_PATH)

    assert response.status_code == OK
    assert response.content == TLS_OK_BODY


def test_sync_client_rejects_untrusted_tls_certificate_and_recovers(
    tls_http_server: TLSServer,
    sync_http_server: str,
) -> None:
    with foghttp.Client() as client:
        with pytest.raises(foghttp.RequestError) as exc_info:
            client.get(tls_http_server.url + TLS_PATH)

        stats_after_failure = client.stats()
        recovery_response = client.get(sync_http_server)
        final_stats = client.stats()

    assert not isinstance(exc_info.value, foghttp.TimeoutError)
    assert_tls_failure_stats(stats_after_failure)
    assert recovery_response.status_code == OK
    assert_recovered_after_tls_failure(final_stats)


def test_sync_tls_handshake_timeout_releases_transport_state_and_recovers(
    tls_handshake_stall_server: TLSHandshakeStallServer,
    sync_http_server: str,
) -> None:
    with foghttp.Client(timeouts=TLS_HANDSHAKE_TIMEOUTS) as client:
        with pytest.raises(foghttp.TimeoutError, match="request total timeout expired") as exc_info:
            client.get(tls_handshake_stall_server.url + TLS_PATH)

        tls_handshake_stall_server.wait_for_connections(1)
        wait_for_sync_transport_stats(
            client,
            lambda stats: stats.active_requests == 0 and stats.pending_requests == 0,
            message="TLS handshake timeout did not release request slots",
        )
        stats_after_timeout = client.stats()
        recovery_response = client.get(sync_http_server, timeout=TLS_RECOVERY_TIMEOUTS)
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
