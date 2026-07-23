__all__ = ("normalize_domain", "normalize_origin")

from ipaddress import ip_address
import re
from urllib.parse import urlsplit

from ..url import URL


_MAX_DOMAIN_LENGTH = 253
_DOMAIN_LABEL_PATTERN = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_DOMAIN_PATTERN = re.compile(rf"{_DOMAIN_LABEL_PATTERN}(?:\.{_DOMAIN_LABEL_PATTERN})*\Z")
_FORBIDDEN_DOMAIN_CHARACTERS = frozenset((":", "/", "?", "#", "@", "[", "]", "*", "%", "\\"))
_FORBIDDEN_ORIGIN_CHARACTERS = frozenset(("%", "\\", "@", "?", "#"))


def normalize_origin(value: object, *, item_error: str, value_error: str) -> str:
    if not isinstance(value, str | URL):
        raise TypeError(item_error)
    return _parse_origin(str(value), value_error)


def normalize_domain(value: object, *, item_error: str, value_error: str) -> str:
    if not isinstance(value, str):
        raise TypeError(item_error)

    invalid_shape = not value or value != value.strip()
    invalid_boundaries = value.startswith(".") or value.endswith(".")
    invalid_characters = _contains_invalid_characters(value, _FORBIDDEN_DOMAIN_CHARACTERS)
    if invalid_shape or invalid_boundaries or invalid_characters:
        raise ValueError(value_error)
    return _parse_domain(value, value_error)


def _parse_origin(value: str, error_message: str) -> str:
    if not _is_strict_origin_input(value):
        raise ValueError(error_message)
    try:
        parsed = URL(value)
    except ValueError as error:
        raise ValueError(error_message) from error

    canonical = str(parsed)
    valid_scheme = parsed.scheme in ("http", "https")
    valid_shape = canonical in (parsed.origin, f"{parsed.origin}/")
    valid_host = _has_unambiguous_ip_host(value, parsed.host)
    if not valid_scheme or not valid_shape or not valid_host:
        raise ValueError(error_message)
    return parsed.origin


def _parse_domain(value: str, error_message: str) -> str:
    try:
        host = URL(f"http://{value}").host
    except ValueError as error:
        raise ValueError(error_message) from error

    try:
        ip_address(host)
    except ValueError:
        is_ip_address = False
    else:
        is_ip_address = True

    valid_domain = len(host) <= _MAX_DOMAIN_LENGTH and _DOMAIN_PATTERN.fullmatch(host) is not None
    if is_ip_address or not valid_domain:
        raise ValueError(error_message)
    return host


def _is_strict_origin_input(value: str) -> bool:
    if value != value.strip() or _contains_invalid_characters(value, _FORBIDDEN_ORIGIN_CHARACTERS):
        return False

    scheme, separator, authority_and_path = value.partition("://")
    if not separator or not scheme:
        return False
    authority = authority_and_path.removesuffix("/")
    return bool(authority) and "/" not in authority and not authority.endswith(":")


def _has_unambiguous_ip_host(value: str, normalized_host: str) -> bool:
    try:
        normalized_address = ip_address(normalized_host)
    except ValueError:
        return True

    original_host = urlsplit(value).hostname
    if original_host is None:
        return False
    try:
        return ip_address(original_host) == normalized_address
    except ValueError:
        return False


def _contains_invalid_characters(value: str, forbidden: frozenset[str]) -> bool:
    has_whitespace = any(map(str.isspace, value))
    has_forbidden = not forbidden.isdisjoint(value)
    return not value.isprintable() or has_whitespace or has_forbidden
