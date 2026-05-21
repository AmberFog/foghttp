__all__ = ("assert_timeout_diagnostic",)

import pytest

import foghttp


def assert_timeout_diagnostic(
    error: foghttp.TimeoutError,
    *,
    phase: str,
    origin: str,
    timeout: float,
    redirect_hop: int = 0,
) -> None:
    diagnostic = _assert_timeout_diagnostic_present(error.diagnostic)
    _assert_value("phase", diagnostic.phase, phase)
    _assert_value("origin", diagnostic.origin, origin)
    _assert_value("timeout", diagnostic.timeout, pytest.approx(timeout))
    if diagnostic.elapsed < 0:
        msg = f"elapsed: expected non-negative value, got {diagnostic.elapsed}"
        raise AssertionError(msg)
    _assert_value("redirect_hop", diagnostic.redirect_hop, redirect_hop)
    _assert_value("error.phase", error.phase, diagnostic.phase)
    _assert_value("error.origin", error.origin, diagnostic.origin)
    _assert_value("error.timeout", error.timeout, diagnostic.timeout)
    _assert_value("error.redirect_hop", error.redirect_hop, diagnostic.redirect_hop)


def _assert_timeout_diagnostic_present(
    diagnostic: foghttp.TimeoutDiagnostic | None,
) -> foghttp.TimeoutDiagnostic:
    if diagnostic is None:
        msg = "expected timeout diagnostic"
        raise AssertionError(msg)
    return diagnostic


def _assert_value(name: str, actual: object, expected: object) -> None:
    if actual != expected:
        msg = f"{name}: expected {expected}, got {actual}"
        raise AssertionError(msg)
