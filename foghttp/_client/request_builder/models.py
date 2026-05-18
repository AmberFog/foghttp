__all__ = ("RequestBuildOptions",)

from dataclasses import dataclass
from typing import Any

from ...headers import HeaderSource
from ...types import QueryParams, RequestData
from ...url import URL


@dataclass(frozen=True, slots=True)
class RequestBuildOptions:
    method: str
    url: str | URL
    headers: HeaderSource = None
    params: QueryParams = None
    content: bytes | str | None = None
    data: RequestData = None
    json: Any = None
