__all__ = (
    "TLSCertificateBundle",
    "create_tls_certificate_bundle",
)

from dataclasses import dataclass
from pathlib import Path

import trustme

from .constants import (
    CA_CERTIFICATE_FILENAME,
    SERVER_CERTIFICATE_FILENAME,
    SERVER_KEY_FILENAME,
    TLS_HOST,
)


@dataclass(frozen=True, slots=True)
class TLSCertificateBundle:
    ca_path: Path
    certificate_path: Path
    key_path: Path


def create_tls_certificate_bundle(directory: Path) -> TLSCertificateBundle:
    ca = trustme.CA()
    server_certificate = ca.issue_cert(TLS_HOST)

    bundle = TLSCertificateBundle(
        ca_path=directory / CA_CERTIFICATE_FILENAME,
        certificate_path=directory / SERVER_CERTIFICATE_FILENAME,
        key_path=directory / SERVER_KEY_FILENAME,
    )
    ca.cert_pem.write_to_path(bundle.ca_path)
    server_certificate.cert_chain_pems[0].write_to_path(bundle.certificate_path)
    server_certificate.private_key_pem.write_to_path(bundle.key_path)
    return bundle
