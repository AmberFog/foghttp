from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import orjson

from .errors import HTTPStatusError
from .messages import http_status_error
from .request_info import RequestInfo
from .status_codes.client_error import MIN_CLIENT_ERROR_STATUS_CODE


__all__ = ("Response",)


@dataclass(frozen=True, slots=True)
class Response:
    status_code: int
    headers: Mapping[str, str]
    content: bytes
    url: str
    request: RequestInfo
    http_version: str
    elapsed: float
    history: tuple["Response", ...] = ()

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding, errors="replace")

    @property
    def encoding(self) -> str:
        content_type = self.headers.get("content-type", "")
        for part in content_type.split(";"):
            key, _, value = part.strip().partition("=")
            if key.lower() == "charset" and value:
                return value.strip("\"'")
        return "utf-8"

    def json(self) -> Any:
        return orjson.loads(self.content)

    def raise_for_status(self) -> None:
        if self.status_code >= MIN_CLIENT_ERROR_STATUS_CODE:
            raise HTTPStatusError(
                http_status_error(
                    self.request.method,
                    self.request.url,
                    self.status_code,
                ),
                response=self,
            )
