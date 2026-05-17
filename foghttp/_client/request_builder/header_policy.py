__all__ = ("TRANSPORT_MANAGED_REQUEST_HEADERS", "validate_safe_request_headers")

from ...headers import Headers
from ...messages import transport_managed_header_error


TRANSPORT_MANAGED_REQUEST_HEADERS = frozenset(
    {
        "connection",
        "content-length",
        "host",
        "keep-alive",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    },
)


def validate_safe_request_headers(headers: Headers) -> None:
    for name, _value in headers.multi_items():
        if name.lower() in TRANSPORT_MANAGED_REQUEST_HEADERS:
            raise ValueError(transport_managed_header_error(name))
