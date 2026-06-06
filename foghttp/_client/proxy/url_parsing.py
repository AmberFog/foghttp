__all__ = (
    "split_proxy_url",
    "split_url",
    "validate_proxy_url_shape",
    "validated_host",
    "validated_port",
)

from typing import NoReturn
from urllib.parse import SplitResult, urlsplit

from .constants import DEFAULT_PROXY_PORTS, MAX_PORT, MIN_PORT, SUPPORTED_PROXY_SCHEMES


def split_proxy_url(value: str, *, source: str) -> SplitResult:
    parts = split_url(value, source=source)
    if not parts.scheme:
        _raise_invalid_proxy_url(source, "must include a scheme")
    if parts.scheme.lower() not in SUPPORTED_PROXY_SCHEMES:
        _raise_invalid_proxy_url(source, "scheme must be http or https")
    return parts


def split_url(value: str, *, source: str) -> SplitResult:
    try:
        return urlsplit(value)
    except ValueError as error:
        msg = f"{source} is invalid"
        raise ValueError(msg) from error


def validated_host(parts: SplitResult, *, source: str) -> str:
    try:
        host = parts.hostname
    except ValueError as error:
        msg = f"{source} host is invalid"
        raise ValueError(msg) from error
    if host is None:
        _raise_invalid_proxy_url(source, "must include a host")
    return host.lower()


def validated_port(parts: SplitResult, *, scheme: str, source: str) -> int:
    try:
        port = parts.port
    except ValueError as error:
        msg = f"{source} port is invalid"
        raise ValueError(msg) from error
    if port is None:
        return DEFAULT_PROXY_PORTS[scheme]
    if port < MIN_PORT or port > MAX_PORT:
        _raise_invalid_proxy_url(source, f"port must be between {MIN_PORT} and {MAX_PORT}")
    return port


def validate_proxy_url_shape(parts: SplitResult, *, source: str) -> None:
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        _raise_invalid_proxy_url(source, "must not include path, query or fragment")


def _raise_invalid_proxy_url(source: str, reason: str) -> NoReturn:
    msg = f"{source} {reason}"
    raise ValueError(msg)
