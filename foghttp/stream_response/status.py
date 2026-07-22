__all__ = ("StreamResponseStatusMixin",)

from typing import TYPE_CHECKING

from foghttp._response.status import (
    is_client_error_status,
    is_error_status,
    is_redirect_status,
    is_server_error_status,
    is_success_status,
)
from foghttp.errors import HTTPStatusError
from foghttp.messages import http_status_error
from foghttp.request_info import RequestInfo


if TYPE_CHECKING:
    from foghttp.retry_trace import RetryTrace


class StreamResponseStatusMixin:
    status_code: int
    request: RequestInfo
    _retry_trace: "RetryTrace | None"

    @property
    def retry_trace(self) -> "RetryTrace | None":
        return self._retry_trace

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

    def raise_for_status(self) -> None:
        if self.is_error:
            raise HTTPStatusError(
                http_status_error(
                    self.request.method,
                    self.request.url,
                    self.status_code,
                ),
                response=self,
                retry_trace=self.retry_trace,
            )
