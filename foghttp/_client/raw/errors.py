__all__ = ("public_raw_error", "raise_public_raw_error")

from typing import NoReturn

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from ...errors import FogHTTPError, LifecycleError, RequestError
from ...errors.response import ResponseBodyBudgetExceededError, ResponseBodyTooLargeError, ResponseError
from ...errors.timeout import PoolTimeout, ReadTimeout, TimeoutError, WriteTimeout
from .timeout_errors import timeout_error_from_raw


_RESPONSE_ERROR_TYPES = (
    (_foghttp.FogHttpResponseBodyTooLargeError, ResponseBodyTooLargeError),
    (_foghttp.FogHttpResponseBodyBudgetExceededError, ResponseBodyBudgetExceededError),
)
_TIMEOUT_ERROR_TYPES = (
    (_foghttp.FogHttpPoolTimeoutError, PoolTimeout),
    (_foghttp.FogHttpReadTimeoutError, ReadTimeout),
    (_foghttp.FogHttpWriteTimeoutError, WriteTimeout),
    (_foghttp.FogHttpTimeoutError, TimeoutError),
)
_LIFECYCLE_ERROR_TYPES = (_foghttp.FogHttpLifecycleError,)


def public_raw_error(exc: BaseException) -> FogHTTPError:
    if _is_lifecycle_error(exc):
        return LifecycleError(str(exc))

    response_error_type = _response_error_type(exc)
    if response_error_type is not None:
        return response_error_type(str(exc))

    timeout_error_type = _timeout_error_type(exc)
    if timeout_error_type is not None:
        return timeout_error_from_raw(exc, timeout_error_type)

    return RequestError(str(exc))


def raise_public_raw_error(exc: BaseException) -> NoReturn:
    raise public_raw_error(exc) from exc


def _response_error_type(exc: BaseException) -> type[ResponseError] | None:
    for raw_error_type, public_error_type in _RESPONSE_ERROR_TYPES:
        if isinstance(exc, raw_error_type):
            return public_error_type
    return None


def _is_lifecycle_error(exc: BaseException) -> bool:
    return isinstance(exc, _LIFECYCLE_ERROR_TYPES)


def _timeout_error_type(exc: BaseException) -> type[TimeoutError] | None:
    for raw_error_type, public_error_type in _TIMEOUT_ERROR_TYPES:
        if isinstance(exc, raw_error_type):
            return public_error_type
    return None
