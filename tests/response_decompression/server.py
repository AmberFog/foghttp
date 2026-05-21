__all__ = (
    "ResponseDecompressionServer",
    "start_response_decompression_server",
)

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from typing import Self, TypeAlias
from urllib.parse import urlsplit

from foghttp.status_codes.client_error import NOT_FOUND
from foghttp.status_codes.success import OK, RESET_CONTENT

from .constants import (
    BODY_CONTENT_TYPE,
    BROTLI_ENCODING_PATH,
    DECODED_TOO_LARGE_BODY,
    DECODED_TOO_LARGE_PATH,
    GZIP_ENCODING_PATH,
    INVALID_GZIP_BODY,
    INVALID_GZIP_PATH,
    MULTIPLE_ENCODING_FIELDS_PATH,
    RAW_DEFLATE_ENCODING_PATH,
    RESET_CONTENT_PATH,
    UNSUPPORTED_ENCODED_BODY,
    UNSUPPORTED_ENCODING,
    UNSUPPORTED_ENCODING_PATH,
    ZLIB_DEFLATE_ENCODING_PATH,
)
from .payloads import compressed_body, gzip_body, multiple_encoding_fields_body


SERVER_HOST = "127.0.0.1"
SERVER_JOIN_TIMEOUT = 1.0
ContentEncodingHeader: TypeAlias = str | tuple[str, ...]


@dataclass(slots=True)
class ResponseDecompressionServer:
    server: ThreadingHTTPServer
    thread: threading.Thread

    @property
    def url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=SERVER_JOIN_TIMEOUT)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()


def start_response_decompression_server() -> ResponseDecompressionServer:
    server = ThreadingHTTPServer((SERVER_HOST, 0), ResponseDecompressionHandler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return ResponseDecompressionServer(server=server, thread=thread)


class ResponseDecompressionHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in ENCODED_PATHS:
            self._write_encoded_response(path)
            return
        if path == UNSUPPORTED_ENCODING_PATH:
            self._write_response(
                UNSUPPORTED_ENCODED_BODY,
                content_encoding=UNSUPPORTED_ENCODING,
            )
            return
        if path == INVALID_GZIP_PATH:
            self._write_response(INVALID_GZIP_BODY, content_encoding="gzip")
            return
        if path == DECODED_TOO_LARGE_PATH:
            self._write_response(
                gzip_body(DECODED_TOO_LARGE_BODY),
                content_encoding="gzip",
            )
            return
        if path == MULTIPLE_ENCODING_FIELDS_PATH:
            self._write_response(
                multiple_encoding_fields_body(),
                content_encoding=("gzip", "deflate"),
            )
            return
        if path == RESET_CONTENT_PATH:
            self._write_encoded_metadata_response(RESET_CONTENT, content_encoding="gzip")
            return

        self._write_empty_response(NOT_FOUND)

    def do_HEAD(self) -> None:
        path = urlsplit(self.path).path
        if path in ENCODED_PATHS:
            self._write_encoded_response(path, write_body=False)
            return

        self._write_empty_response(NOT_FOUND)

    def _write_encoded_response(self, path: str, *, write_body: bool = True) -> None:
        self._write_response(
            compressed_body(path),
            content_encoding=ENCODED_RESPONSE_ENCODINGS[path],
            write_body=write_body,
        )

    def _write_response(
        self,
        body: bytes,
        *,
        content_encoding: ContentEncodingHeader,
        write_body: bool = True,
    ) -> None:
        self.send_response(OK)
        self.send_header("content-type", BODY_CONTENT_TYPE)
        for value in _content_encoding_values(content_encoding):
            self.send_header("content-encoding", value)
        self.send_header("content-length", str(len(body)))
        self.send_header("connection", "close")
        self.end_headers()
        if write_body:
            self.wfile.write(body)

    def _write_encoded_metadata_response(
        self,
        status_code: int,
        *,
        content_encoding: str,
    ) -> None:
        self.send_response(status_code)
        self.send_header("content-encoding", content_encoding)
        self.send_header("content-length", "0")
        self.send_header("connection", "close")
        self.end_headers()

    def _write_empty_response(self, status_code: int) -> None:
        self.send_response(status_code)
        self.send_header("content-length", "0")
        self.send_header("connection", "close")
        self.end_headers()


ENCODED_RESPONSE_ENCODINGS = {
    BROTLI_ENCODING_PATH: "br",
    GZIP_ENCODING_PATH: "gzip",
    RAW_DEFLATE_ENCODING_PATH: "deflate",
    ZLIB_DEFLATE_ENCODING_PATH: "deflate",
}
ENCODED_PATHS = frozenset(ENCODED_RESPONSE_ENCODINGS)


def _content_encoding_values(content_encoding: ContentEncodingHeader) -> tuple[str, ...]:
    if isinstance(content_encoding, str):
        return (content_encoding,)
    return content_encoding
