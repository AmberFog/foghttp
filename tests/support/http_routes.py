__all__ = (
    "ECHO_HEADERS_PATH",
    "OBS_TEXT_HEADERS_PATH",
    "REDIRECT_TO_LOCATION_PATH",
    "REPEATED_HEADERS_PATH",
    "SECURITY_HEADERS_PATH",
    "TEXT_PATH",
    "bytes_response_size",
    "redirect_status",
    "redirect_to_location",
    "redirect_to_status",
    "status_code",
    "unknown_size_bytes_response_size",
)

from urllib.parse import parse_qs


BYTES_PATH_PARTS = 2
REDIRECT_PATH_PARTS = 2
REDIRECT_TO_STATUS_PATH_PARTS = 3
STATUS_PATH_PARTS = 2
UNKNOWN_SIZE_BYTES_ROUTE = "unknown-size-bytes"

ECHO_HEADERS_PATH = "/headers/echo"
OBS_TEXT_HEADERS_PATH = "/headers/obs-text"
REDIRECT_TO_LOCATION_PATH = "/redirect-to-location"
REPEATED_HEADERS_PATH = "/headers/repeated"
SECURITY_HEADERS_PATH = "/headers/security"
TEXT_PATH = "/text"


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
