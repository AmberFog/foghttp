from dataclasses import fields

import pytest

import foghttp
from foghttp._validation.numeric import MAX_NUMERIC_OPTION
from foghttp.limits import DEFAULT_MAX_TOTAL_UPLOAD_BUFFER_BYTES, DEFAULT_MAX_UPLOAD_BUFFER_BYTES


UPLOAD_LIMIT_FIELDS = ("max_upload_buffer_bytes", "max_total_upload_buffer_bytes")


@pytest.mark.parametrize("field_name", UPLOAD_LIMIT_FIELDS)
@pytest.mark.parametrize(
    "value",
    [
        pytest.param(None, id="none"),
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
        pytest.param(True, id="bool"),
        pytest.param(1.5, id="float"),
        pytest.param("64", id="string"),
        pytest.param(MAX_NUMERIC_OPTION + 1, id="too-large"),
    ],
)
def test_upload_buffer_limits_require_finite_positive_integers(field_name: str, value: object) -> None:
    with pytest.raises(ValueError, match=rf"Limits\.{field_name} must be an integer between 1 and"):
        foghttp.Limits(**{field_name: value})


@pytest.mark.parametrize("value", [1, MAX_NUMERIC_OPTION])
def test_upload_buffer_limits_accept_supported_boundaries(value: int) -> None:
    limits = foghttp.Limits(max_upload_buffer_bytes=value, max_total_upload_buffer_bytes=value)

    assert limits.max_upload_buffer_bytes == value
    assert limits.max_total_upload_buffer_bytes == value


def test_upload_buffer_limits_have_finite_defaults_and_preserve_positional_arguments() -> None:
    previous_fields = [item.name for item in fields(foghttp.Limits) if item.name not in UPLOAD_LIMIT_FIELDS]
    defaults = foghttp.Limits()
    values = [getattr(defaults, name) for name in previous_fields]
    limits = foghttp.Limits(*values)

    assert limits.max_upload_buffer_bytes == DEFAULT_MAX_UPLOAD_BUFFER_BYTES == 512 * 1024
    assert limits.max_total_upload_buffer_bytes == DEFAULT_MAX_TOTAL_UPLOAD_BUFFER_BYTES == 16 * 1024 * 1024
    assert limits == defaults
