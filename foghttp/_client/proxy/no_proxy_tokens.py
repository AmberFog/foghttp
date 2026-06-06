__all__ = (
    "is_ip_literal",
    "normalize_rule_host",
    "normalize_target_host",
    "split_no_proxy_host_port",
)

from ipaddress import IPv6Address, ip_address

from .constants import MAX_PORT, MIN_PORT


def split_no_proxy_host_port(value: str) -> tuple[str, int | None]:
    if value.startswith("["):
        return _split_bracketed_host_port(value)
    if value.count(":") == 1:
        host, port = value.rsplit(":", maxsplit=1)
        return host, _parse_no_proxy_port(port)
    return value, None


def normalize_rule_host(value: str) -> str:
    host = value.strip().lower().rstrip(".")
    host = host.removeprefix("*.")
    return host.removeprefix(".")


def normalize_target_host(value: str) -> str:
    return value.strip("[]").lower().rstrip(".")


def is_ip_literal(value: str) -> bool:
    try:
        ip_address(value)
    except ValueError:
        return False
    return True


def _split_bracketed_host_port(value: str) -> tuple[str, int | None]:
    bracket_index = value.find("]")
    if bracket_index < 0:
        msg = "NO_PROXY IPv6 rule is missing closing bracket"
        raise ValueError(msg)
    host = value[1:bracket_index]
    _validate_bracketed_ipv6_host(host)
    suffix = value[bracket_index + 1 :]
    if not suffix:
        return host, None
    if not suffix.startswith(":"):
        msg = "NO_PROXY IPv6 rule suffix is invalid"
        raise ValueError(msg)
    return host, _parse_no_proxy_port(suffix[1:])


def _validate_bracketed_ipv6_host(host: str) -> None:
    try:
        IPv6Address(host)
    except ValueError as error:
        msg = "NO_PROXY bracketed host must be an IPv6 address"
        raise ValueError(msg) from error


def _parse_no_proxy_port(value: str) -> int:
    if not value.isdigit():
        msg = "NO_PROXY port must be an integer"
        raise ValueError(msg)
    port = int(value)
    if port < MIN_PORT or port > MAX_PORT:
        msg = f"NO_PROXY port must be between {MIN_PORT} and {MAX_PORT}"
        raise ValueError(msg)
    return port
