__all__ = ("RequestBuildOptions",)

from dataclasses import dataclass
from typing import Any

from ..._upload_body import AsyncRequestContent, SyncRequestContent
from ...headers import HeaderSource
from ...types import AsyncMultipartFiles, QueryParams, RequestData, SyncMultipartFiles
from ...url import URL


@dataclass(frozen=True, slots=True)
class RequestBuildOptions:
    method: str
    url: str | URL
    headers: HeaderSource = None
    params: QueryParams = None
    content: SyncRequestContent | AsyncRequestContent | None = None
    data: RequestData = None
    files: SyncMultipartFiles | AsyncMultipartFiles | None = None
    json: Any = None
