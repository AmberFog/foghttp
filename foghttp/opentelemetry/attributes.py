import os
import re

from .. import errors
from ..methods import HTTP_METHODS


_METHOD_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_ERROR_CLASSES = (
    errors.ConnectTimeout,
    errors.ReadTimeout,
    errors.WriteTimeout,
    errors.PoolTimeout,
    errors.TimeoutError,
    errors.ResponseBodyTooLargeError,
    errors.ResponseBodyBudgetExceededError,
    errors.ResponseDecodingError,
    errors.SSRFError,
    errors.NetworkError,
    errors.ClientClosedError,
    errors.ConfigurationError,
    errors.RequestError,
    errors.ResponseError,
    errors.LifecycleError,
    errors.FogHTTPError,
)


def known_methods() -> frozenset[str]:
    configured = os.environ.get("OTEL_INSTRUMENTATION_HTTP_KNOWN_METHODS")
    if configured is None:
        return frozenset(HTTP_METHODS)
    methods = frozenset(method.strip() for method in configured.split(","))
    if not all(_METHOD_TOKEN.fullmatch(method) for method in methods):
        msg = "OTEL_INSTRUMENTATION_HTTP_KNOWN_METHODS must contain nonempty HTTP tokens"
        raise errors.ConfigurationError(msg)
    return methods


def error_type(error: Exception) -> str:
    for error_class in _ERROR_CLASSES:
        if isinstance(error, error_class):
            return error_class.__name__
    return "_OTHER"
