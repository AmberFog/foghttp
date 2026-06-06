__all__ = (
    "ALL_PROXY_ENV_NAMES",
    "DEFAULT_PROXY_PORTS",
    "DEFAULT_TARGET_PORTS",
    "HTTPS_PROXY_ENV_NAMES",
    "HTTP_PROXY_ENV_NAMES",
    "MAX_PORT",
    "MIN_PORT",
    "NO_PROXY_ENV_NAMES",
    "REQUEST_METHOD_ENV_NAME",
    "SSL_CERT_FILE_ENV_NAMES",
    "SUPPORTED_PROXY_SCHEMES",
)

from types import MappingProxyType


ALL_PROXY_ENV_NAMES = ("all_proxy", "ALL_PROXY")
HTTP_PROXY_ENV_NAMES = ("http_proxy", "HTTP_PROXY")
HTTPS_PROXY_ENV_NAMES = ("https_proxy", "HTTPS_PROXY")
NO_PROXY_ENV_NAMES = ("no_proxy", "NO_PROXY")
REQUEST_METHOD_ENV_NAME = "REQUEST_METHOD"
SSL_CERT_FILE_ENV_NAMES = ("ssl_cert_file", "SSL_CERT_FILE")
MIN_PORT = 1
MAX_PORT = 65535
DEFAULT_PROXY_PORTS = MappingProxyType(
    {
        "http": 80,
    },
)
DEFAULT_TARGET_PORTS = MappingProxyType(
    {
        "http": 80,
        "https": 443,
    },
)
SUPPORTED_PROXY_SCHEMES = frozenset(DEFAULT_PROXY_PORTS)
