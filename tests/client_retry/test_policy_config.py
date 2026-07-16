from collections.abc import Collection
from typing import cast

import pytest

import foghttp


DEFAULT_BACKOFF = 0.1
DEFAULT_JITTER = 0.1
DEFAULT_RETRIES = 2


def test_retry_policy_defaults_are_safe_and_explicit() -> None:
    policy = foghttp.RetryPolicy()

    assert policy.retries == DEFAULT_RETRIES
    assert policy.backoff == DEFAULT_BACKOFF
    assert policy.jitter == DEFAULT_JITTER
    assert policy.retry_on.statuses == frozenset({429, 502, 503, 504})
    assert policy.retry_on.exceptions == (foghttp.NetworkError,)
    assert policy.methods == frozenset({"GET", "HEAD", "OPTIONS", "QUERY", "TRACE"})
    assert "POST" not in policy.methods


def test_retry_policy_normalizes_conditions_and_methods() -> None:
    conditions = foghttp.RetryConditions(
        statuses=(503, 503, 429),
        exceptions=(foghttp.NetworkError, foghttp.NetworkError),
    )
    policy = foghttp.RetryPolicy(
        retries=1,
        backoff=0,
        jitter=0,
        retry_on=conditions,
        methods=("get", "GET", "custom-method"),
    )

    assert policy.retry_on is conditions
    assert policy.retry_on.statuses == frozenset({429, 503})
    assert policy.retry_on.exceptions == (foghttp.NetworkError,)
    assert policy.methods == frozenset({"GET", "CUSTOM-METHOD"})


@pytest.mark.parametrize(
    ("statuses", "error_type"),
    [
        pytest.param("503", TypeError, id="string-collection"),
        pytest.param(cast("Collection[int]", iter((503,))), TypeError, id="iterator"),
        pytest.param((True,), TypeError, id="boolean-item"),
        pytest.param(cast("Collection[int]", (503.0,)), TypeError, id="non-integer-item"),
        pytest.param((99,), ValueError, id="below-range"),
        pytest.param((600,), ValueError, id="above-range"),
    ],
)
def test_retry_conditions_reject_invalid_statuses(
    statuses: Collection[int],
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        foghttp.RetryConditions(statuses=statuses)


@pytest.mark.parametrize(
    ("exceptions", "error_type"),
    [
        pytest.param(foghttp.NetworkError, TypeError, id="single-exception-type"),
        pytest.param((foghttp.RequestError,), ValueError, id="unsupported-exception"),
    ],
)
def test_retry_conditions_reject_invalid_exceptions(
    exceptions: Collection[type[foghttp.NetworkError]],
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        foghttp.RetryConditions(exceptions=exceptions)


@pytest.mark.parametrize(
    ("methods", "error_type"),
    [
        pytest.param("GET", TypeError, id="string-collection"),
        pytest.param(cast("Collection[str]", iter(("GET",))), TypeError, id="iterator"),
        pytest.param(cast("Collection[str]", (1,)), TypeError, id="non-string-item"),
        pytest.param(("",), ValueError, id="empty-token"),
        pytest.param(("NOT A METHOD",), ValueError, id="invalid-token"),
        pytest.param(("M\u00c9THODE",), ValueError, id="non-ascii-token"),
    ],
)
def test_retry_policy_rejects_invalid_methods(
    methods: Collection[str],
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        foghttp.RetryPolicy(methods=methods)


def test_retry_policy_rejects_invalid_retry_conditions_object() -> None:
    with pytest.raises(TypeError, match="retry_on must be RetryConditions"):
        foghttp.RetryPolicy(retry_on=cast("foghttp.RetryConditions", object()))


@pytest.mark.parametrize(
    "options",
    [
        pytest.param({"retries": -1}, id="negative-retries"),
        pytest.param({"retries": True}, id="boolean-retries"),
        pytest.param({"backoff": float("inf")}, id="infinite-backoff"),
        pytest.param({"jitter": -1.0}, id="negative-jitter"),
    ],
)
def test_retry_policy_rejects_invalid_numeric_options(options: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="must be"):
        foghttp.RetryPolicy(**options)  # type: ignore[arg-type]
