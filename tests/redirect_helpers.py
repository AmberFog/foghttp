__all__ = (
    "REDIRECT_SECURITY_HEADERS",
    "SECURITY_HEADERS_PATH",
    "header_values",
    "redirect_to_location_url",
)

from typing import Any, cast
from urllib.parse import urlencode


SECURITY_HEADERS_PATH = "/headers/security"
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
