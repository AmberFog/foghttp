__all__ = ("budget_below_decoding_transient_size",)

from .constants import DECODED_TOO_LARGE_BODY
from .payloads import gzip_body


def budget_below_decoding_transient_size() -> int:
    encoded_size = len(gzip_body(DECODED_TOO_LARGE_BODY))
    decoded_size = len(DECODED_TOO_LARGE_BODY)
    return encoded_size + decoded_size - 1
