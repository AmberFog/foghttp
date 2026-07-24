__all__ = (
    "COOKIE_BODY_PATH",
    "COOKIE_EXPIRE_PATH",
    "COOKIE_OPAQUE_PATH",
    "COOKIE_PATH_SET_PATH",
    "COOKIE_REDIRECT_PATH",
    "COOKIE_RETRY_PATH",
    "COOKIE_ROOT_SET_PATH",
    "ECHO_HEADERS_PATH",
    "OBS_TEXT_HEADERS_PATH",
    "REDIRECT_TO_LOCATION_PATH",
    "REPEATED_HEADERS_PATH",
    "SECURITY_HEADERS_PATH",
    "TEXT_PATH",
    "bytes_response_size",
    "cookie_response",
    "redirect_status",
    "redirect_to_location",
    "redirect_to_status",
    "status_code",
    "unknown_size_bytes_response_size",
)

from urllib.parse import parse_qs

from foghttp.status_codes.redirect import FOUND
from foghttp.status_codes.server_error import SERVICE_UNAVAILABLE
from foghttp.status_codes.success import OK


BYTES_PATH_PARTS = 2
REDIRECT_PATH_PARTS = 2
REDIRECT_TO_STATUS_PATH_PARTS = 3
STATUS_PATH_PARTS = 2
UNKNOWN_SIZE_BYTES_ROUTE = "unknown-size-bytes"

COOKIE_BODY_PATH = "/cookies/body"
COOKIE_EXPIRE_PATH = "/cookies/expire"
COOKIE_OPAQUE_PATH = "/cookies/opaque"
COOKIE_PATH_SET_PATH = "/cookies/path"
COOKIE_REDIRECT_PATH = "/cookies/redirect"
COOKIE_RETRY_PATH = "/cookies/retry"
COOKIE_ROOT_SET_PATH = "/cookies/root"
ECHO_HEADERS_PATH = "/headers/echo"
OBS_TEXT_HEADERS_PATH = "/headers/obs-text"
REDIRECT_TO_LOCATION_PATH = "/redirect-to-location"
REPEATED_HEADERS_PATH = "/headers/repeated"
SECURITY_HEADERS_PATH = "/headers/security"
TEXT_PATH = "/text"


def cookie_response(
    path: str,
    query: str,
    request_cookies: list[str],
) -> tuple[int, list[tuple[str, str]], bytes] | None:
    if path == COOKIE_PATH_SET_PATH:
        response = OK, [("set-cookie", "scoped=cookie-secret; Path=/headers")], b""
    elif path == COOKIE_BODY_PATH:
        response = (
            OK,
            [("set-cookie", "retry_session=cookie-secret; Path=/")],
            b"x" * 4096,
        )
    elif path == COOKIE_OPAQUE_PATH:
        response = (
            OK,
            [
                ("set-cookie", "opaque=%41%2F%25; Path=/"),
                ("set-cookie", 'quoted="a%2Fb"; Path=/'),
                ("set-cookie", "literal=100%; Path=/"),
                ("set-cookie", "encoded=%FF; Path=/"),
                ("set-cookie", "latin=\xe9; Path=/"),
                ("set-cookie", "empty=; Path=/"),
                ("set-cookie", "equals=a=b; Path=/"),
                ("set-cookie", "nameless-token; Path=/"),
                ("set-cookie", "ascii=sibling; Path=/"),
            ],
            b"",
        )
    elif path == COOKIE_ROOT_SET_PATH:
        response = OK, [("set-cookie", "root=cookie-secret; Path=/")], b""
    elif path == COOKIE_EXPIRE_PATH:
        response = OK, [("set-cookie", "root=; Path=/; Max-Age=0")], b""
    elif path == COOKIE_REDIRECT_PATH:
        locations = parse_qs(query, keep_blank_values=True).get("location", [])
        if locations:
            response = (
                FOUND,
                [
                    ("location", locations[0]),
                    ("set-cookie", "redirect_session=cookie-secret; Path=/"),
                ],
                b"",
            )
        else:
            response = None
    elif path == COOKIE_RETRY_PATH:
        if any("retry_session=cookie-secret" in value for value in request_cookies):
            response = OK, [], b""
        else:
            response = (
                SERVICE_UNAVAILABLE,
                [
                    ("set-cookie", "retry_session=cookie-secret; Path=/"),
                ],
                b"",
            )
    else:
        response = None
    return response


def redirect_status(path: str) -> int | None:
    parts = path.strip("/").split("/")
    if len(parts) == REDIRECT_PATH_PARTS and parts[0] == "redirect":
        return int(parts[1])
    return None


def redirect_to_status(path: str) -> tuple[int, int] | None:
    parts = path.strip("/").split("/")
    if len(parts) == REDIRECT_TO_STATUS_PATH_PARTS and parts[0] == "redirect-to-status":
        return int(parts[1]), int(parts[2])
    return None


def redirect_to_location(path: str, query: str) -> tuple[int, str] | None:
    if path != REDIRECT_TO_LOCATION_PATH:
        return None

    params = parse_qs(query, keep_blank_values=True)
    status_values = params.get("status", [])
    location_values = params.get("location", [])
    if not status_values or not location_values:
        return None
    return int(status_values[0]), location_values[0]


def status_code(path: str) -> int | None:
    parts = path.strip("/").split("/")
    if len(parts) == STATUS_PATH_PARTS and parts[0] == "status":
        return int(parts[1])
    return None


def bytes_response_size(path: str) -> int | None:
    parts = path.strip("/").split("/")
    if len(parts) == BYTES_PATH_PARTS and parts[0] == "bytes":
        return int(parts[1])
    return None


def unknown_size_bytes_response_size(path: str) -> int | None:
    parts = path.strip("/").split("/")
    if len(parts) == BYTES_PATH_PARTS and parts[0] == UNKNOWN_SIZE_BYTES_ROUTE:
        return int(parts[1])
    return None
