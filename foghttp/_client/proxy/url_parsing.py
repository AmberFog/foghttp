__all__ = (
    "split_proxy_url",
    "split_url",
    "validate_proxy_url_shape",
    "validated_host",
    "validated_port",
)

from collections.abc import Mapping
from typing import NoReturn
from urllib.parse import SplitResult, urlsplit

from . import constants as proxy_constants


def split_proxy_url(value: str, *, source: str) -> SplitResult:
    parts = split_url(value, source=source)
    if not parts.scheme:
        _raise_invalid_proxy_url(source, proxy_constants.PROXY_URL_SCHEME_REQUIRED_REASON)
    if parts.scheme.lower() not in proxy_constants.SUPPORTED_PROXY_SCHEMES:
        _raise_invalid_proxy_url(source, proxy_constants.PROXY_URL_SCHEME_UNSUPPORTED_REASON)
    return parts


def split_url(value: str, *, source: str) -> SplitResult:
    try:
        return urlsplit(value)
    except ValueError as error:
        msg = f"{source} {proxy_constants.PROXY_URL_INVALID_REASON}"
        raise ValueError(msg) from error


def validated_host(parts: SplitResult, *, source: str) -> str:
    try:
        host = parts.hostname
    except ValueError as error:
        msg = f"{source} {proxy_constants.PROXY_URL_HOST_INVALID_REASON}"
        raise ValueError(msg) from error
    if host is None:
        _raise_invalid_proxy_url(source, proxy_constants.PROXY_URL_HOST_REQUIRED_REASON)
    return host.lower()


def validated_port(
    parts: SplitResult,
    *,
    scheme: str,
    source: str,
    default_ports: Mapping[str, int] = proxy_constants.DEFAULT_PROXY_PORTS,
) -> int:
    try:
        port = parts.port
    except ValueError as error:
        msg = f"{source} {proxy_constants.PROXY_URL_PORT_INVALID_REASON}"
        raise ValueError(msg) from error
    if port is None:
        return default_ports[scheme]
    if port < proxy_constants.MIN_PORT or port > proxy_constants.MAX_PORT:
        _raise_invalid_proxy_url(source, proxy_constants.PROXY_URL_PORT_RANGE_REASON)
    return port


def validate_proxy_url_shape(parts: SplitResult, *, source: str) -> None:
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        _raise_invalid_proxy_url(source, proxy_constants.PROXY_URL_SHAPE_UNSUPPORTED_REASON)


def _raise_invalid_proxy_url(source: str, reason: str) -> NoReturn:
    msg = f"{source} {reason}"
    raise ValueError(msg)
