from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import orjson

from .errors import HTTPStatusError
from .messages import http_status_error


MIN_ERROR_STATUS_CODE = 400


@dataclass(frozen=True, slots=True)
class Response:
    status_code: int
    headers: Mapping[str, str]
    content: bytes
    url: str
    http_version: str
    elapsed: float

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
        if self.status_code >= MIN_ERROR_STATUS_CODE:
            raise HTTPStatusError(
                http_status_error(self.status_code, self.url),
                response=self,
            )
