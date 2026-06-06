__all__ = ("clear_proxy_environment",)

import pytest

from foghttp._client.proxy.constants import (
    ALL_PROXY_ENV_NAMES,
    HTTP_PROXY_ENV_NAMES,
    HTTPS_PROXY_ENV_NAMES,
    NO_PROXY_ENV_NAMES,
    REQUEST_METHOD_ENV_NAME,
    SSL_CERT_FILE_ENV_NAMES,
)


def clear_proxy_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        *ALL_PROXY_ENV_NAMES,
        *HTTP_PROXY_ENV_NAMES,
        *HTTPS_PROXY_ENV_NAMES,
        *NO_PROXY_ENV_NAMES,
        *SSL_CERT_FILE_ENV_NAMES,
        REQUEST_METHOD_ENV_NAME,
    ):
        monkeypatch.delenv(name, raising=False)
