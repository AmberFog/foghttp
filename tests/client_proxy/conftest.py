__all__ = (
    "async_http_proxy",
    "connect_proxy",
    "sync_http_proxy",
    "tls_target",
)

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.client_proxy.connect_proxy_server import ConnectProxy, start_connect_proxy
from tests.client_proxy.http_proxy_server import async_http_proxy, sync_http_proxy
from tests.client_tls.certificates import TLSCertificateBundle, create_tls_certificate_bundle
from tests.client_tls.models import TLSServer
from tests.client_tls.server import start_tls_server


@pytest.fixture
def tls_target(tmp_path: Path) -> Iterator[tuple[TLSServer, TLSCertificateBundle]]:
    bundle = create_tls_certificate_bundle(tmp_path)
    with start_tls_server(bundle) as server:
        yield server, bundle


@pytest.fixture
def connect_proxy() -> Iterator[ConnectProxy]:
    proxy = start_connect_proxy()
    try:
        yield proxy
    finally:
        proxy.close()
