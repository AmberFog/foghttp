__all__ = ("Request",)

from typing import TYPE_CHECKING

from ._redaction import redact_url
from ._request_body import RequestBody
from ._upload_body import SyncRequestContent, normalize_content_body
from .headers import Headers, HeaderSource
from .request_extensions import (
    RequestExtensions,
    RequestExtensionsSource,
    empty_request_extensions,
    normalize_request_extensions,
)
from .url import URL


if TYPE_CHECKING:
    from ._auth_headers import AuthHeaderProvenance


_EMPTY_REQUEST_EXTENSIONS = empty_request_extensions()


class Request:
    method: str
    url: str

    __slots__ = (
        "_auth_header_provenance",
        "_body",
        "_extensions",
        "_headers",
        "method",
        "url",
    )

    def __init__(
        self,
        method: str,
        url: str | URL,
        *,
        headers: HeaderSource = None,
        content: SyncRequestContent | object | None = None,
        extensions: RequestExtensionsSource = None,
    ) -> None:
        self.method = method.upper()
        self.url = str(URL(url))
        self._auth_header_provenance: AuthHeaderProvenance | None = None
        self._headers = Headers(headers)
        self._extensions = _EMPTY_REQUEST_EXTENSIONS if extensions is None else normalize_request_extensions(extensions)
        self._body = normalize_content_body(content)

    @property
    def content(self) -> bytes | None:
        return self._body.content

    @content.setter
    def content(self, value: bytes | None) -> None:
        self._body = RequestBody.replayable_body(value)

    @property
    def extensions(self) -> RequestExtensions:
        return self._extensions

    @property
    def headers(self) -> Headers:
        return self._headers

    @headers.setter
    def headers(self, value: Headers) -> None:
        self._headers = value
        if self._auth_header_provenance is not None:
            self._auth_header_provenance.replace(value)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.method!r}, {redact_url(self.url)!r})"
