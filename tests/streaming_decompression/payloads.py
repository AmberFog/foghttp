__all__ = ("EncodedResponse", "gated_gzip", "gzip_bytes", "nested_gzip")

from dataclasses import dataclass
import gzip
from http import HTTPStatus
import zlib

from .constants import FIRST_OUTPUT, TAIL_OUTPUT


@dataclass(frozen=True, slots=True)
class EncodedResponse:
    body: bytes
    encodings: tuple[str, ...] = ("gzip",)
    status: int = HTTPStatus.OK
    gate_after: int | None = None
    close_before_tail: bool = False


def gzip_bytes(body: bytes) -> bytes:
    return gzip.compress(body, mtime=0)


def nested_gzip(body: bytes, layers: int) -> bytes:
    for _layer in range(layers):
        body = gzip_bytes(body)
    return body


def gated_gzip() -> EncodedResponse:
    compressor = zlib.compressobj(wbits=zlib.MAX_WBITS | 16)
    prefix = compressor.compress(FIRST_OUTPUT) + compressor.flush(zlib.Z_SYNC_FLUSH)
    tail = compressor.compress(TAIL_OUTPUT) + compressor.flush()
    return EncodedResponse(prefix + tail, gate_after=len(prefix))
