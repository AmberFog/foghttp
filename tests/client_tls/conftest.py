from collections.abc import Iterator
from pathlib import Path

import pytest

from .certificates import TLSCertificateBundle, create_tls_certificate_bundle
from .models import TLSServer
from .server import start_tls_server


@pytest.fixture
def tls_certificates(tmp_path: Path) -> TLSCertificateBundle:
    return create_tls_certificate_bundle(tmp_path)


@pytest.fixture
def unrelated_tls_certificates(tmp_path: Path) -> TLSCertificateBundle:
    directory = tmp_path / "unrelated-ca"
    directory.mkdir()
    return create_tls_certificate_bundle(directory)


@pytest.fixture
def tls_http_server(tls_certificates: TLSCertificateBundle) -> Iterator[TLSServer]:
    with start_tls_server(tls_certificates) as server:
        yield server
