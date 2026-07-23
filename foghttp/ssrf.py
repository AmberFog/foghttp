__all__ = ("SSRFPolicy",)

from collections.abc import Collection
from dataclasses import dataclass

from ._validation.ssrf import normalize_domain, normalize_origin
from .url import URL


_DEFAULT_ALLOWED_SCHEMES = ("http", "https")
_COLLECTION_ERROR = "{field} must be a collection"
_DOMAIN_ITEM_ERROR = "SSRFPolicy.allowed_domains must contain domain name strings"
_DOMAIN_VALUE_ERROR = "SSRFPolicy.allowed_domains must contain valid domain names"
_ORIGIN_ITEM_ERROR = "SSRFPolicy.allowed_origins must contain URL or string origins"
_ORIGIN_VALUE_ERROR = "SSRFPolicy.allowed_origins must contain origin-only HTTP(S) URLs"
_SCHEME_ITEM_ERROR = "SSRFPolicy.allowed_schemes must contain strings"
_SCHEME_VALUE_ERROR = "SSRFPolicy.allowed_schemes supports only 'http' and 'https'"
_SCHEMES_EMPTY_ERROR = "SSRFPolicy.allowed_schemes must not be empty"


@dataclass(frozen=True, init=False, slots=True)
class SSRFPolicy:
    """Opt-in destination policy for requests that may contain untrusted URLs.

    Destination allowlists narrow the targets accepted by the client. Resolved
    DNS addresses must still be public. An exact origin containing an IP
    literal may explicitly trust that address, including a private address.
    """

    allowed_schemes: frozenset[str]
    allowed_origins: frozenset[str]
    allowed_domains: frozenset[str]

    def __init__(
        self,
        *,
        allowed_schemes: Collection[str] = _DEFAULT_ALLOWED_SCHEMES,
        allowed_origins: Collection[str | URL] = (),
        allowed_domains: Collection[str] = (),
    ) -> None:
        schemes = _normalize_schemes(allowed_schemes)
        origins = _normalize_origins(allowed_origins)
        if any(URL(origin).scheme not in schemes for origin in origins):
            raise ValueError(_SCHEME_VALUE_ERROR)

        object.__setattr__(self, "allowed_schemes", schemes)
        object.__setattr__(self, "allowed_origins", origins)
        object.__setattr__(self, "allowed_domains", _normalize_domains(allowed_domains))


def _normalize_schemes(schemes: Collection[str]) -> frozenset[str]:
    _validate_collection("SSRFPolicy.allowed_schemes", schemes)
    normalized: set[str] = set()
    for scheme in schemes:
        if not isinstance(scheme, str):
            raise TypeError(_SCHEME_ITEM_ERROR)
        if scheme != scheme.strip() or scheme.lower() not in _DEFAULT_ALLOWED_SCHEMES:
            raise ValueError(_SCHEME_VALUE_ERROR)
        normalized.add(scheme.lower())
    if not normalized:
        raise ValueError(_SCHEMES_EMPTY_ERROR)
    return frozenset(normalized)


def _normalize_origins(origins: Collection[str | URL]) -> frozenset[str]:
    _validate_collection("SSRFPolicy.allowed_origins", origins)
    return frozenset(
        normalize_origin(
            origin,
            item_error=_ORIGIN_ITEM_ERROR,
            value_error=_ORIGIN_VALUE_ERROR,
        )
        for origin in origins
    )


def _normalize_domains(domains: Collection[str]) -> frozenset[str]:
    _validate_collection("SSRFPolicy.allowed_domains", domains)
    return frozenset(
        normalize_domain(
            domain,
            item_error=_DOMAIN_ITEM_ERROR,
            value_error=_DOMAIN_VALUE_ERROR,
        )
        for domain in domains
    )


def _validate_collection(field: str, value: object) -> None:
    if isinstance(value, str | bytes) or not isinstance(value, Collection):
        raise TypeError(_COLLECTION_ERROR.format(field=field))
