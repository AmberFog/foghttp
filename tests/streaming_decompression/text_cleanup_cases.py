__all__ = ("GZIP_FOOTER_BYTES", "PRIMARY_TEXT_FAILURES", "TERMINAL_EVENTS", "TextFailureCase")

from dataclasses import dataclass

import pytest

import foghttp


GZIP_FOOTER_BYTES = 8
TERMINAL_EVENTS = (
    foghttp.TelemetryEventType.RESPONSE_BODY_FINISHED,
    foghttp.TelemetryEventType.REQUEST_FINISHED,
)


@dataclass(frozen=True, slots=True)
class TextFailureCase:
    body: bytes
    error_type: type[Exception]
    match: str
    lines: bool = False
    line_limit: int | None = None


PRIMARY_TEXT_FAILURES = (
    pytest.param(TextFailureCase(b"\xffunread", UnicodeDecodeError, "invalid start byte"), id="text-invalid-utf8"),
    pytest.param(
        TextFailureCase(b"\xffunread", UnicodeDecodeError, "invalid start byte", lines=True),
        id="lines-invalid-utf8",
    ),
    pytest.param(
        TextFailureCase(b"alpha\nunread", foghttp.ResponseError, "max_line_chars=4", lines=True, line_limit=4),
        id="lines-over-limit",
    ),
)
