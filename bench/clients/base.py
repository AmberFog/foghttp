__all__ = ("AsyncClientAdapter", "SyncClientAdapter")

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from bench.models import ResponseOutcome, Scenario


class AsyncClientAdapter:
    async def request(self, scenario: "Scenario", url: str) -> "ResponseOutcome":
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    def stats(self) -> dict[str, Any] | None:
        return None


class SyncClientAdapter:
    def request(self, scenario: "Scenario", url: str) -> "ResponseOutcome":
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def stats(self) -> dict[str, Any] | None:
        return None
