__all__ = ("raise_public_raw_error",)

from typing import NoReturn

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from ...errors import (
    PoolTimeout,
    ReadTimeout,
    RequestError,
    ResponseBodyBudgetExceededError,
    ResponseBodyTooLargeError,
    TimeoutError,
)
from .timeout_errors import timeout_error_from_raw


def raise_public_raw_error(exc: BaseException) -> NoReturn:
    if isinstance(exc, _foghttp.FogHttpResponseBodyTooLargeError):
        raise ResponseBodyTooLargeError(str(exc)) from exc
    if isinstance(exc, _foghttp.FogHttpResponseBodyBudgetExceededError):
        raise ResponseBodyBudgetExceededError(str(exc)) from exc
    if isinstance(exc, _foghttp.FogHttpPoolTimeoutError):
        raise timeout_error_from_raw(exc, PoolTimeout) from exc
    if isinstance(exc, _foghttp.FogHttpReadTimeoutError):
        raise timeout_error_from_raw(exc, ReadTimeout) from exc
    if isinstance(exc, _foghttp.FogHttpTimeoutError):
        raise timeout_error_from_raw(exc, TimeoutError) from exc
    raise RequestError(str(exc)) from exc
