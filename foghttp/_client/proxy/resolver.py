__all__ = ("ProxyResolver", "ProxyRules")

from dataclasses import dataclass, field

from .models import ProxyDecision, ProxySource, ProxyTarget, ProxyUrl
from .no_proxy import NoProxyMatcher


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
        return cls(explicit=ProxyRules(http=proxy), environment=environment)

    @classmethod
    def from_environment(cls, rules: ProxyRules) -> "ProxyResolver":
        return cls(explicit=None, environment=rules)

    def http_proxy(self) -> ProxyUrl | None:
        if self.explicit is not None:
            explicit_proxy = self.explicit.proxy_for_scheme("http")
            if explicit_proxy is not None:
                return explicit_proxy
        if self.environment is None:
            return None
        return self.environment.proxy_for_scheme("http")

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
