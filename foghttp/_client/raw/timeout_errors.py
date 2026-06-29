__all__ = ("timeout_error_from_raw",)

from dataclasses import dataclass
from typing import Self

from ...errors import TimeoutError
from ...timeout_diagnostics import TimeoutDiagnostic, TimeoutPhase


_TIMEOUT_DIAGNOSTIC_ARG_COUNT = 6


@dataclass(frozen=True, slots=True)
class _RawTimeoutDiagnostic:
    message: object
    phase: object
    elapsed: object
    timeout: object
    origin: object
    redirect_hop: object

    @classmethod
    def from_exception(cls, exc: BaseException) -> Self | None:
        args = _raw_exception_args(exc)
        if len(args) != _TIMEOUT_DIAGNOSTIC_ARG_COUNT:
            return None
        return cls(*args)

    def public_diagnostic(self) -> TimeoutDiagnostic | None:
        phase = _coerce_timeout_phase(self.phase)
        elapsed = _coerce_timeout_float(self.elapsed)
        timeout = _coerce_timeout_float(self.timeout)
        redirect_hop = _coerce_timeout_int(self.redirect_hop)
        if phase is None or elapsed is None or timeout is None or redirect_hop is None:
            return None

        return TimeoutDiagnostic(
            phase=phase,
            elapsed=elapsed,
            timeout=timeout,
            origin=str(self.origin),
            redirect_hop=redirect_hop,
        )


def timeout_error_from_raw(
    exc: BaseException,
    error_type: type[TimeoutError],
) -> TimeoutError:
    raw_diagnostic = _RawTimeoutDiagnostic.from_exception(exc)
    if raw_diagnostic is None:
        return error_type(_raw_exception_message(exc), diagnostic=None)
    return error_type(
        str(raw_diagnostic.message),
        diagnostic=raw_diagnostic.public_diagnostic(),
    )


def _raw_exception_args(exc: BaseException) -> tuple[object, ...]:
    if len(exc.args) == 1 and isinstance(exc.args[0], tuple):
        return exc.args[0]
    return exc.args


def _raw_exception_message(exc: BaseException) -> str:
    if not exc.args:
        return str(exc)
    return str(exc.args[0])


def _coerce_timeout_phase(value: object) -> TimeoutPhase | None:
    match str(value):
        case "pool_acquire":
            return "pool_acquire"
        case "request_body":
            return "request_body"
        case "response_headers":
            return "response_headers"
        case "response_body":
            return "response_body"
    return None


def _coerce_timeout_float(value: object) -> float | None:
    if not isinstance(value, str | bytes | bytearray | int | float):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_timeout_int(value: object) -> int | None:
    if not isinstance(value, str | bytes | bytearray | int):
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None
