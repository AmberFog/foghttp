__all__ = (
    "BROKEN_READY_TAIL_STREAM_PATH",
    "EMPTY_STREAM_PATH",
    "ENTER_STREAM_TIMEOUT",
    "FIRST_CHUNK",
    "GATED_STREAM_PATH",
    "LATIN1_TEXT_STREAM_PATH",
    "LATIN1_TEXT_VALUE",
    "PENDING_READ_START_DELAY",
    "READ_TIMEOUT_SECONDS",
    "SECOND_CHUNK",
    "SLOW_TAIL_DELAY",
    "SLOW_TAIL_STREAM_PATH",
    "STREAM_NETWORK_ERROR_TIMEOUTS",
    "STREAM_READ_TIMEOUT",
    "TAIL_WAIT_TIMEOUT",
    "TEXT_LINES",
    "TEXT_LINES_BODY",
    "TEXT_LINES_STREAM_CHUNKS",
    "TEXT_LINES_STREAM_PATH",
)

import foghttp


BROKEN_READY_TAIL_STREAM_PATH = "/stream/broken-ready-tail"
EMPTY_STREAM_PATH = "/stream/empty"
ENTER_STREAM_TIMEOUT = 1.0
FIRST_CHUNK = b"first-stream-chunk"
GATED_STREAM_PATH = "/stream/gated"
LATIN1_TEXT_STREAM_PATH = "/stream/text-latin1"
LATIN1_TEXT_VALUE = "M\u00fcnchen\n"
PENDING_READ_START_DELAY = 0.02
READ_TIMEOUT_SECONDS = 0.05
SECOND_CHUNK = b"second-stream-chunk"
SLOW_TAIL_DELAY = 0.25
SLOW_TAIL_STREAM_PATH = "/stream/slow-tail"
STREAM_NETWORK_ERROR_TIMEOUTS = foghttp.Timeouts(connect=0.2, pool=0.2, total=1.0)
STREAM_READ_TIMEOUT = 1.0
TAIL_WAIT_TIMEOUT = 5.0
TEXT_LINES = ("M\u00fcnchen", "second", "", "final-no-newline")
TEXT_LINES_BODY = "M\u00fcnchen\r\nsecond\n\nfinal-no-newline"
TEXT_LINES_STREAM_CHUNKS = (
    b"M\xc3",
    b"\xbcnchen\r",
    b"\nsecond",
    b"\n\nfinal-no-newline",
)
TEXT_LINES_STREAM_PATH = "/stream/text-lines"
