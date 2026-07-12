__all__ = (
    "REDIRECT_CONDITIONAL_HEADERS",
    "REDIRECT_CONTENT_HEADERS",
    "REDIRECT_SECURITY_HEADERS",
    "SECURITY_HEADERS_PATH",
    "header_values",
    "redirect_to_location_url",
)

from typing import Any, cast
from urllib.parse import urlencode


SECURITY_HEADERS_PATH = "/headers/security"
REDIRECT_CONDITIONAL_HEADERS = {
    "if-match": '"request-etag"',
    "if-modified-since": "Mon, 01 Jan 2024 00:00:00 GMT",
    "if-none-match": '"cached-etag"',
    "if-range": '"range-etag"',
    "if-unmodified-since": "Mon, 01 Jan 2024 00:00:00 GMT",
}
REDIRECT_CONTENT_HEADERS = {
    "content-checksum": "custom-checksum",
    "content-digest": "sha-256=:YWJj:",
    "content-disposition": "attachment; filename=payload.txt",
    "content-encoding": "identity",
    "content-language": "en",
    "content-location": "/source",
    "content-range": "bytes 0-2/3",
    "content-type": "text/plain",
    "digest": "sha-256=Z2hp",
    "last-modified": "Mon, 01 Jan 2024 00:00:00 GMT",
    "repr-digest": "sha-256=:ZGVm:",
}
REDIRECT_SECURITY_HEADERS = {
    "accept": "application/json",
    "authorization": "Bearer secret",
    "cookie": "session=secret",
    "origin": "https://example.com",
    "referer": "https://example.com/source",
}


def redirect_to_location_url(base_url: str, *, status_code: int, location: str) -> str:
    query = urlencode({"status": status_code, "location": location})
    return f"{base_url}/redirect-to-location?{query}"


def header_values(payload: dict[str, Any], name: str) -> list[str]:
    return cast("list[str]", payload["headers"][name])
