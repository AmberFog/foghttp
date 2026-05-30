__all__ = (
    "assert_lifecycle_error_is_actionable",
    "assert_url_is_redacted",
)

from .lifecycle_debug_data import (
    QUERY_REDACTED_VALUE_ONE,
    QUERY_REDACTED_VALUE_TWO,
    SENSITIVE_USERNAME,
    USERINFO_REDACTED_VALUE,
    VISIBLE_QUERY_VALUE,
)


def assert_url_is_redacted(value: str) -> None:
    leaked_values = (
        SENSITIVE_USERNAME,
        USERINFO_REDACTED_VALUE,
        QUERY_REDACTED_VALUE_ONE,
        QUERY_REDACTED_VALUE_TWO,
    )
    leaked_value = next((secret for secret in leaked_values if secret in value), None)
    if leaked_value is not None:
        raise AssertionError(value)
    if f"safe={VISIBLE_QUERY_VALUE}" not in value:
        raise AssertionError(value)
    if "<redacted>" not in value:
        raise AssertionError(value)


def assert_lifecycle_error_is_actionable(message: str) -> None:
    expected_fragments = (
        "active_requests=(",
        "1:GET",
        "age_ms=",
        "omitted_active_requests=0",
    )
    missing_fragments = tuple(fragment for fragment in expected_fragments if fragment not in message)
    if missing_fragments:
        raise AssertionError(message)
