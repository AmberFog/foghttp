from collections.abc import Mapping
from dataclasses import dataclass


__all__ = ("RequestInfo",)


@dataclass(frozen=True, slots=True)
class RequestInfo:
    method: str
    url: str
    headers: Mapping[str, str]
