__all__ = ("ProxyTransportPolicy",)

from enum import StrEnum


class ProxyTransportPolicy(StrEnum):
    DIRECT = "direct"
    EXPLICIT_PROXY = "explicit_proxy"
    ENVIRONMENT_PROXY = "environment_proxy"
