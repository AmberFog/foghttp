__all__ = (
    "MAX_NUMERIC_OPTION",
    "validate_non_negative_int",
    "validate_non_negative_seconds",
    "validate_optional_non_negative_int",
)

import math
from typing import TypeGuard


MAX_NUMERIC_OPTION = 2**31 - 1


def validate_non_negative_int(name: str, value: int) -> int:
    if not _is_valid_int_option(value):
        msg = f"{name} must be an integer between 0 and {MAX_NUMERIC_OPTION}"
        raise ValueError(msg)
    return value


def validate_optional_non_negative_int(name: str, value: int | None) -> int | None:
    if value is None:
        return None
    return validate_non_negative_int(name, value)


def validate_non_negative_seconds(name: str, value: float) -> float:
    is_valid_type = not isinstance(value, bool) and isinstance(value, int | float)
    seconds = float(value) if is_valid_type else math.nan

    if not is_valid_type or not math.isfinite(seconds) or seconds < 0.0 or seconds > MAX_NUMERIC_OPTION:
        raise ValueError(_seconds_error(name))

    return seconds


def _seconds_error(name: str) -> str:
    return f"{name} must be a finite number between 0 and {MAX_NUMERIC_OPTION}"


def _is_valid_int_option(value: object) -> bool:
    return _is_int_option(value) and 0 <= value <= MAX_NUMERIC_OPTION


def _is_int_option(value: object) -> TypeGuard[int]:
    return not isinstance(value, bool) and isinstance(value, int)
