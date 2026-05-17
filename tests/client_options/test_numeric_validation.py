import math

import pytest

import foghttp
from foghttp.limits import DEFAULT_MAX_RESPONSE_BODY_SIZE


MAX_INVALID_NUMERIC_OPTION = 2**31

TIMEOUT_FIELDS = ("connect", "read", "write", "pool", "total")
INTEGER_LIMIT_FIELDS = (
    "max_active_requests",
    "max_active_requests_per_origin",
    "max_pending_requests",
    "max_response_body_size",
    "max_idle_connections_per_host",
)


def test_limits_use_safe_default_response_body_size() -> None:
    assert foghttp.Limits().max_response_body_size == DEFAULT_MAX_RESPONSE_BODY_SIZE


@pytest.mark.parametrize("field_name", TIMEOUT_FIELDS)
@pytest.mark.parametrize(
    "value",
    [
        pytest.param(math.nan, id="nan"),
        pytest.param(math.inf, id="infinity"),
        pytest.param(-0.1, id="negative"),
        pytest.param(MAX_INVALID_NUMERIC_OPTION, id="too-large"),
        pytest.param(True, id="bool"),
    ],
)
def test_timeouts_reject_invalid_numeric_values(field_name: str, value: object) -> None:
    with pytest.raises(
        ValueError,
        match=rf"Timeouts\.{field_name} must be a finite number between 0 and",
    ):
        foghttp.Timeouts(**{field_name: value})


@pytest.mark.parametrize("field_name", INTEGER_LIMIT_FIELDS)
@pytest.mark.parametrize(
    "value",
    [
        pytest.param(-1, id="negative"),
        pytest.param(MAX_INVALID_NUMERIC_OPTION, id="too-large"),
        pytest.param(1.5, id="float"),
        pytest.param(True, id="bool"),
    ],
)
def test_limits_reject_invalid_integer_values(field_name: str, value: object) -> None:
    with pytest.raises(
        ValueError,
        match=rf"Limits\.{field_name} must be an integer between 0 and",
    ):
        foghttp.Limits(**{field_name: value})


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(math.nan, id="nan"),
        pytest.param(math.inf, id="infinity"),
        pytest.param(-0.1, id="negative"),
        pytest.param(MAX_INVALID_NUMERIC_OPTION, id="too-large"),
        pytest.param(True, id="bool"),
    ],
)
def test_limits_reject_invalid_idle_timeout(value: object) -> None:
    with pytest.raises(
        ValueError,
        match=r"Limits\.idle_timeout must be a finite number between 0 and",
    ):
        foghttp.Limits(idle_timeout=value)


def test_limits_accept_zero_for_explicit_backpressure_edges() -> None:
    limits = foghttp.Limits(
        max_active_requests=0,
        max_active_requests_per_origin=0,
        max_pending_requests=0,
        max_response_body_size=0,
        max_idle_connections_per_host=0,
        idle_timeout=0,
    )

    assert limits.max_active_requests == 0
    assert limits.max_active_requests_per_origin == 0
    assert limits.max_pending_requests == 0
    assert limits.max_response_body_size == 0
    assert limits.max_idle_connections_per_host == 0
    assert limits.idle_timeout == 0.0


def test_optional_limit_fields_accept_none() -> None:
    limits = foghttp.Limits(
        max_active_requests_per_origin=None,
        max_response_body_size=None,
    )

    assert limits.max_active_requests_per_origin is None
    assert limits.max_response_body_size is None
