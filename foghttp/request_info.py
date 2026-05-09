__all__ = ("RequestInfo",)

from dataclasses import dataclass

from .headers import Headers


@dataclass(frozen=True, slots=True)
class RequestInfo:
    method: str
    url: str
    headers: Headers
