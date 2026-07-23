__all__ = ("ssrf_error_from_raw",)

from ...errors import SSRFError, SSRFViolationReason


_SSRF_ERROR_ARG_COUNT = 2


def ssrf_error_from_raw(exc: BaseException) -> SSRFError:
    args = _raw_exception_args(exc)
    if len(args) != _SSRF_ERROR_ARG_COUNT:
        return SSRFError(_raw_exception_message(exc), reason=SSRFViolationReason.UNKNOWN)

    message, raw_reason = args
    try:
        reason = SSRFViolationReason(str(raw_reason))
    except ValueError:
        reason = SSRFViolationReason.UNKNOWN
    return SSRFError(str(message), reason=reason)


def _raw_exception_args(exc: BaseException) -> tuple[object, ...]:
    if len(exc.args) == 1 and isinstance(exc.args[0], tuple):
        return exc.args[0]
    return exc.args


def _raw_exception_message(exc: BaseException) -> str:
    args = _raw_exception_args(exc)
    if not args:
        return str(exc)
    return str(args[0])
