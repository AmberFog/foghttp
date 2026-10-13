__all__ = (
    "DECODED_BODY",
    "FIRST_OUTPUT",
    "GZIP_RESERVATION",
    "IDENTITY_RESERVATION",
    "LARGE_BODY",
    "TAIL_OUTPUT",
    "TEXT_BODY",
    "WAIT_TIMEOUT",
)


DECODED_BODY = b"streaming content decoding\r\nsecond line\nlast line"
TEXT_BODY = "first: \u00e9\r\nsecond: \u20ac\nlast: \U0001f642"
FIRST_OUTPUT = b"first decoded chunk\n"
TAIL_OUTPUT = b"second decoded chunk\n"
LARGE_BODY = b"bounded output\n" * 32768
IDENTITY_RESERVATION = 2 * 64 * 1024
GZIP_RESERVATION = 1024 * 1024 + 3 * 64 * 1024
WAIT_TIMEOUT = 5.0
