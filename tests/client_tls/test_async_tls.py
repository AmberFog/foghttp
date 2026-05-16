import pytest

import foghttp
from foghttp.status_codes.success import OK

from .assertions import assert_recovered_after_tls_failure, assert_tls_failure_stats
from .certificates import TLSCertificateBundle
from .constants import TLS_OK_BODY, TLS_PATH
from .models import TLSServer


async def test_async_client_accepts_custom_ca_certificate(
    tls_certificates: TLSCertificateBundle,
    tls_http_server: TLSServer,
) -> None:
    tls = foghttp.TLSConfig(ca_certificates=(tls_certificates.ca_path,))

    async with foghttp.AsyncClient(tls=tls) as client:
        response = await client.get(tls_http_server.url + TLS_PATH)

    assert response.status_code == OK
    assert response.content == TLS_OK_BODY


async def test_async_client_rejects_untrusted_tls_certificate_and_recovers(
    tls_http_server: TLSServer,
    http_server: str,
) -> None:
    async with foghttp.AsyncClient() as client:
        with pytest.raises(foghttp.RequestError) as exc_info:
            await client.get(tls_http_server.url + TLS_PATH)

        stats_after_failure = client.stats()
        recovery_response = await client.get(http_server)
        final_stats = client.stats()

    assert not isinstance(exc_info.value, foghttp.TimeoutError)
    assert_tls_failure_stats(stats_after_failure)
    assert recovery_response.status_code == OK
    assert_recovered_after_tls_failure(final_stats)
