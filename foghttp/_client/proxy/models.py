__all__ = (
    "ProxyDecision",
    "ProxySource",
    "ProxyTarget",
    "ProxyUrl",
)

from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urlunsplit

from ..._redaction import REDACTED_VALUE
from .constants import DEFAULT_PROXY_PORTS
from .url_parsing import (
    split_proxy_url,
    split_url,
    validate_proxy_url_shape,
    validated_host,
    validated_port,
)


class ProxySource(StrEnum):
    NONE = "none"
    EXPLICIT = "explicit"
    ENVIRONMENT = "environment"
    NO_PROXY = "no_proxy"


@dataclass(frozen=True, slots=True)
class ProxyCredentials:
    """Internal raw proxy credentials. Do not log or expose directly."""

    username: str = field(repr=False)
    password: str | None = field(repr=False)

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        return f"{class_name}({REDACTED_VALUE!r})"


@dataclass(frozen=True, slots=True)
class ProxyUrl:
    """Validated proxy endpoint. ``endpoint_url`` never contains credentials."""

    endpoint_url: str
    scheme: str
    host: str
    port: int
    endpoint_netloc: str
    credentials: ProxyCredentials | None

    @classmethod
    def parse(cls, value: str, *, source: str = "proxy URL") -> "ProxyUrl":
        parts = split_proxy_url(value, source=source)
        scheme = parts.scheme.lower()
        host = validated_host(parts, source=source)
        port = validated_port(parts, scheme=scheme, source=source)
        validate_proxy_url_shape(parts, source=source)
        endpoint_netloc = _proxy_endpoint_netloc(host, port)
        return cls(
            endpoint_url=urlunsplit((scheme, endpoint_netloc, "", "", "")),
            scheme=scheme,
            host=host,
            port=port,
            endpoint_netloc=endpoint_netloc,
            credentials=_proxy_credentials(parts.username, parts.password),
        )

    @property
    def redacted_url(self) -> str:
        if self.credentials is None:
            return self.endpoint_url
        return urlunsplit((self.scheme, f"{REDACTED_VALUE}@{self.endpoint_netloc}", "", "", ""))

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        return f"{class_name}({self.redacted_url!r})"


@dataclass(frozen=True, slots=True)
class ProxyTarget:
    scheme: str
    host: str
    port: int

    @classmethod
    def parse(cls, value: str) -> "ProxyTarget":
        parts = split_url(value, source="target URL")
        scheme = parts.scheme.lower()
        if scheme not in DEFAULT_PROXY_PORTS:
            msg = "target URL scheme must be http or https"
            raise ValueError(msg)
        host = validated_host(parts, source="target URL")
        port = validated_port(parts, scheme=scheme, source="target URL")
        return cls(scheme=scheme, host=host, port=port)


@dataclass(frozen=True, slots=True)
class ProxyDecision:
    target: ProxyTarget
    proxy: ProxyUrl | None
    source: ProxySource
    no_proxy_rule: str | None = None

    @property
    def uses_proxy(self) -> bool:
        return self.proxy is not None


def _proxy_credentials(
    username: str | None,
    password: str | None,
) -> ProxyCredentials | None:
    if username is None and password is None:
        return None
    return ProxyCredentials(username="" if username is None else username, password=password)


def _proxy_endpoint_netloc(host: str, port: int) -> str:
    if ":" in host:
        return f"[{host}]:{port}"
    return f"{host}:{port}"
