import pytest

import foghttp
from foghttp.status_codes.success import OK

from .assertions import assert_recovered_after_tls_failure, assert_tls_failure_stats
from .certificates import TLSCertificateBundle
from .constants import TLS_OK_BODY, TLS_PATH
from .models import TLSServer


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
