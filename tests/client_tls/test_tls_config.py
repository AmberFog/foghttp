from pathlib import Path

import pytest

import foghttp

from .certificates import TLSCertificateBundle
from .constants import TLS_INVALID_CA_BODY, TLS_OK_BODY, TLS_PATH
from .models import TLSServer


def test_client_accepts_single_ca_certificate_path(
    tls_certificates: TLSCertificateBundle,
    tls_http_server: TLSServer,
) -> None:
    tls = foghttp.TLSConfig(ca_certificates=tls_certificates.ca_path)

    with foghttp.Client(tls=tls) as client:
        response = client.get(tls_http_server.url + TLS_PATH)

    assert response.content == TLS_OK_BODY


def test_client_rejects_missing_ca_certificate_file(
    sync_http_server: str,
    tmp_path: Path,
) -> None:
    tls = foghttp.TLSConfig(ca_certificates=(tmp_path / "missing-ca.pem",))

    with (
        foghttp.Client(tls=tls) as client,
        pytest.raises(ValueError, match="failed to read CA certificate"),
    ):
        client.get(sync_http_server)


def test_client_rejects_invalid_ca_certificate_pem(
    sync_http_server: str,
    tmp_path: Path,
) -> None:
    ca_path = tmp_path / "invalid-ca.pem"
    ca_path.write_bytes(TLS_INVALID_CA_BODY)
    tls = foghttp.TLSConfig(ca_certificates=(ca_path,))

    with (
        foghttp.Client(tls=tls) as client,
        pytest.raises(ValueError, match="CA certificate PEM did not contain certificates"),
    ):
        client.get(sync_http_server)
