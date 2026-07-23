__all__ = ("SSRFError", "SSRFViolationReason")

from enum import StrEnum

from .base import RequestError


class SSRFViolationReason(StrEnum):
    """Stable reason why an SSRF policy rejected a request."""

    DESTINATION_NOT_ALLOWED = "destination_not_allowed"
    NON_PUBLIC_ADDRESS = "non_public_address"
    PROXY_RESOLUTION_UNSUPPORTED = "proxy_resolution_unsupported"
    SCHEME_NOT_ALLOWED = "scheme_not_allowed"
    UNKNOWN = "unknown"


class SSRFError(RequestError):
    """Raised when an enabled SSRF policy rejects a request destination."""

    def __init__(
        self,
        message: str,
        *,
        reason: SSRFViolationReason = SSRFViolationReason.UNKNOWN,
    ) -> None:
        super().__init__(message)
        self._reason = reason

    @property
    def reason(self) -> SSRFViolationReason:
        return self._reason
