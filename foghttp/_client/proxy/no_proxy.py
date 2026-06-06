__all__ = ("NoProxyMatcher", "NoProxyRule")

from dataclasses import dataclass

from .models import ProxyTarget
from .no_proxy_rule import NoProxyRule


@dataclass(frozen=True, slots=True)
class NoProxyMatcher:
    rules: tuple[NoProxyRule, ...]

    @classmethod
    def empty(cls) -> "NoProxyMatcher":
        return cls(rules=())

    @classmethod
    def parse(cls, value: str | None) -> "NoProxyMatcher":
        if not value:
            return cls.empty()

        rules: list[NoProxyRule] = []
        for token in value.split(","):
            rule = NoProxyRule.parse(token)
            if rule is not None:
                rules.append(rule)
        return cls(rules=tuple(rules))

    def find_match(self, target: ProxyTarget) -> NoProxyRule | None:
        return next((rule for rule in self.rules if rule.matches(target)), None)

    def matches(self, target: ProxyTarget) -> bool:
        return self.find_match(target) is not None
