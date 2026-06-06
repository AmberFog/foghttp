__all__ = ("NoProxyRule",)

from dataclasses import dataclass

from .models import ProxyTarget
from .no_proxy_tokens import (
    is_ip_literal,
    normalize_rule_host,
    normalize_target_host,
    split_no_proxy_host_port,
)


@dataclass(frozen=True, slots=True)
class NoProxyRule:
    value: str
    host: str
    port: int | None
    wildcard: bool
    suffix_match: bool
    ip_literal: bool

    @classmethod
    def parse(cls, value: str) -> "NoProxyRule | None":
        stripped_value = value.strip()
        if not stripped_value:
            return None
        if stripped_value == "*":
            return cls(
                value=stripped_value,
                host="",
                port=None,
                wildcard=True,
                suffix_match=False,
                ip_literal=False,
            )

        host, port = split_no_proxy_host_port(stripped_value)
        normalized_host = normalize_rule_host(host)
        if "/" in host:
            msg = "NO_PROXY CIDR rules are not supported"
            raise ValueError(msg)
        if _is_malformed_rule_host(host):
            msg = "NO_PROXY host is invalid"
            raise ValueError(msg)
        return cls(
            value=stripped_value,
            host=normalized_host,
            port=port,
            wildcard=False,
            suffix_match=_is_suffix_rule(host, normalized_host),
            ip_literal=is_ip_literal(normalized_host),
        )

    def matches(self, target: ProxyTarget) -> bool:
        if self.wildcard:
            return True
        if self.port is not None and self.port != target.port:
            return False
        return self._matches_host(normalize_target_host(target.host))

    def _matches_host(self, target_host: str) -> bool:
        if self.ip_literal or is_ip_literal(target_host) or not self.suffix_match:
            return target_host == self.host
        return target_host == self.host or target_host.endswith(f".{self.host}")


def _is_suffix_rule(raw_host: str, normalized_host: str) -> bool:
    return raw_host.startswith((".", "*.")) or "." in normalized_host


def _is_malformed_rule_host(raw_host: str) -> bool:
    host = raw_host.strip().lower().rstrip(".")
    if host.startswith("*."):
        host = host.removeprefix("*.")
    elif host.startswith("."):
        host = host.removeprefix(".")
    return not host or host == "*" or "*" in host or "" in host.split(".")
