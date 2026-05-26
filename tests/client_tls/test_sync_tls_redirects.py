from faker import Faker
import pytest

import foghttp
from foghttp.status_codes.redirect import PERMANENT_REDIRECT, TEMPORARY_REDIRECT
from tests.redirect_helpers import SECURITY_HEADERS_PATH, redirect_to_location_url

from .certificates import TLSCertificateBundle
from .models import TLSServer


@pytest.mark.parametrize("status_code", [TEMPORARY_REDIRECT, PERMANENT_REDIRECT])
def test_sync_https_to_http_redirect_with_body_is_blocked(
    tls_certificates: TLSCertificateBundle,
    tls_http_server: TLSServer,
    sync_http_server: str,
    faker: Faker,
    status_code: int,
) -> None:
    tls = foghttp.TLSConfig(ca_certificates=(tls_certificates.ca_path,))
    location = f"{sync_http_server}{SECURITY_HEADERS_PATH}"
    url = redirect_to_location_url(
        tls_http_server.url,
        status_code=status_code,
        location=location,
    )

    with foghttp.Client(follow_redirects=True, tls=tls) as client:
        with pytest.raises(
            foghttp.RequestError,
            match="https-to-http redirect blocked",
        ):
            client.post(
                url,
                headers={"authorization": "Bearer secret"},
                content=faker.sentence(),
            )

        stats_after_error = client.stats()

    assert stats_after_error.total_requests == 1
    assert stats_after_error.failed_requests == 1
    assert stats_after_error.active_requests == 0
    assert stats_after_error.pending_requests == 0
