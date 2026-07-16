__all__ = ("Response",)

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import orjson

from ._redaction import redact_url
from ._response.encoding import response_encoding
from ._response.status import (
    is_client_error_status,
    is_error_status,
    is_redirect_status,
    is_server_error_status,
    is_success_status,
)
from .errors import HTTPStatusError
from .headers import Headers
from .messages import http_status_error
from .request_info import RequestInfo


if TYPE_CHECKING:
    from ._client.retry import RetryDecisionData


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
    _retry_decisions: tuple["RetryDecisionData", ...] = field(
        default=(),
        init=False,
        repr=False,
        compare=False,
    )

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"status_code={self.status_code!r}, "
            f"headers={self.headers!r}, "
            f"content=<{len(self.content)} bytes>, "
            f"url={redact_url(self.url)!r}, "
            f"request={self.request!r}, "
            f"http_version={self.http_version!r}, "
            f"elapsed={self.elapsed!r}, "
            f"history=<{len(self.history)} responses>)"
        )

    @property
    def is_success(self) -> bool:
        return is_success_status(self.status_code)

    @property
    def is_redirect(self) -> bool:
        return is_redirect_status(self.status_code)

    @property
    def is_client_error(self) -> bool:
        return is_client_error_status(self.status_code)

    @property
    def is_server_error(self) -> bool:
        return is_server_error_status(self.status_code)

    @property
    def is_error(self) -> bool:
        return is_error_status(self.status_code)

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding, errors="replace")

    @property
    def encoding(self) -> str:
        return response_encoding(self.headers, self.content)

    def json(self) -> Any:
        return orjson.loads(self.content)

    def raise_for_status(self) -> None:
        if self.is_error:
            raise HTTPStatusError(
                http_status_error(
                    self.request.method,
                    self.request.url,
                    self.status_code,
                ),
                response=self,
            )
