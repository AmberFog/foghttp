__all__ = ("Response",)

from dataclasses import dataclass
from typing import Any

import orjson

from .errors import HTTPStatusError
from .headers import Headers
from .messages import http_status_error
from .request_info import RequestInfo
from .status_codes.client_error import MAX_CLIENT_ERROR_STATUS_CODE, MIN_CLIENT_ERROR_STATUS_CODE
from .status_codes.redirect import MAX_REDIRECT_STATUS_CODE, MIN_REDIRECT_STATUS_CODE
from .status_codes.server_error import MAX_SERVER_ERROR_STATUS_CODE, MIN_SERVER_ERROR_STATUS_CODE
from .status_codes.success import MAX_SUCCESS_STATUS_CODE, MIN_SUCCESS_STATUS_CODE


@dataclass(frozen=True, slots=True)
class Response:
    status_code: int
    headers: Headers
    content: bytes
    url: str
    request: RequestInfo
    http_version: str
    elapsed: float
    history: tuple["Response", ...] = ()

    @property
    def is_success(self) -> bool:
        return MIN_SUCCESS_STATUS_CODE <= self.status_code <= MAX_SUCCESS_STATUS_CODE

    @property
    def is_redirect(self) -> bool:
        return MIN_REDIRECT_STATUS_CODE <= self.status_code <= MAX_REDIRECT_STATUS_CODE

    @property
    def is_client_error(self) -> bool:
        return MIN_CLIENT_ERROR_STATUS_CODE <= self.status_code <= MAX_CLIENT_ERROR_STATUS_CODE

    @property
    def is_server_error(self) -> bool:
        return MIN_SERVER_ERROR_STATUS_CODE <= self.status_code <= MAX_SERVER_ERROR_STATUS_CODE

    @property
    def is_error(self) -> bool:
        return self.is_client_error or self.is_server_error

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
