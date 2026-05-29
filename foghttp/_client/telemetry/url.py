__all__ = ("redacted_url", "url_origin")

from contextlib import suppress

from ..._redaction import redact_url
from ...url import URL


def redacted_url(url: str) -> str:
    return redact_url(url)


def url_origin(url: str) -> str | None:
    with suppress(ValueError):
        return URL(url).origin
    return None
