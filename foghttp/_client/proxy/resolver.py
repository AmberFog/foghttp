__all__ = ("ProxyResolver", "ProxyRules")

from dataclasses import dataclass, field

from .models import ProxyDecision, ProxySource, ProxyTarget, ProxyUrl
from .no_proxy import NoProxyMatcher
from .transport_policy import ProxyTransportPolicy


@dataclass(frozen=True, slots=True)
class ProxyRules:
    http: ProxyUrl | None = None
    https: ProxyUrl | None = None
    all_proxy: ProxyUrl | None = None
    no_proxy: NoProxyMatcher = field(default_factory=NoProxyMatcher.empty)

    def proxy_for_scheme(self, scheme: str) -> ProxyUrl | None:
        if scheme == "http":
            return self.http or self.all_proxy
        if scheme == "https":
            return self.https or self.all_proxy
        return None

    def has_routing_policy(self) -> bool:
        return self.http is not None or self.https is not None or self.all_proxy is not None


@dataclass(frozen=True, slots=True)
class ProxyResolver:
    explicit: ProxyRules | None
    environment: ProxyRules | None

    @classmethod
    def disabled(cls) -> "ProxyResolver":
        return cls(explicit=None, environment=None)

    @classmethod
    def from_explicit(
        cls,
        *,
        proxy: ProxyUrl,
        environment: ProxyRules | None = None,
    ) -> "ProxyResolver":
        return cls(explicit=ProxyRules(http=proxy, https=proxy), environment=environment)

    @classmethod
    def from_environment(cls, rules: ProxyRules) -> "ProxyResolver":
        return cls(explicit=None, environment=rules)

    def routing_proxy(self, scheme: str) -> ProxyUrl | None:
        """Proxy endpoint for a target ``scheme`` (``http`` or ``https``).

        Plain-HTTP targets proxy in absolute-form, HTTPS targets tunnel via
        CONNECT. Explicit ``proxy=`` wins over environment and maps both schemes
        to the same proxy; environment config may set different HTTP and HTTPS
        proxies, which are routed independently.
        """
        rules = self.environment if self.explicit is None else self.explicit
        return None if rules is None else rules.proxy_for_scheme(scheme)

    def transport_policy(self) -> ProxyTransportPolicy:
        if self.explicit is not None:
            return ProxyTransportPolicy.EXPLICIT_PROXY
        if self.environment is not None and self.environment.has_routing_policy():
            return ProxyTransportPolicy.ENVIRONMENT_PROXY
        return ProxyTransportPolicy.DIRECT

    def resolve(self, url: str) -> ProxyDecision:
        target = ProxyTarget.parse(url)
        explicit_proxy = None if self.explicit is None else self.explicit.proxy_for_scheme(target.scheme)
        if explicit_proxy is not None:
            return ProxyDecision(target=target, proxy=explicit_proxy, source=ProxySource.EXPLICIT)

        if self.environment is None:
            return ProxyDecision(target=target, proxy=None, source=ProxySource.NONE)

        no_proxy_rule = self.environment.no_proxy.find_match(target)
        if no_proxy_rule is not None:
            return ProxyDecision(
                target=target,
                proxy=None,
                source=ProxySource.NO_PROXY,
                no_proxy_rule=no_proxy_rule.value,
            )

        environment_proxy = self.environment.proxy_for_scheme(target.scheme)
        if environment_proxy is not None:
            return ProxyDecision(target=target, proxy=environment_proxy, source=ProxySource.ENVIRONMENT)
        return ProxyDecision(target=target, proxy=None, source=ProxySource.NONE)
