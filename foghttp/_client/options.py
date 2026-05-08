__all__ = ("validate_client_options",)

from ..messages import (
    COOKIES_UNSUPPORTED,
    HTTP_VERSION_UNSUPPORTED,
    MAX_REDIRECTS_INVALID,
    TRUST_ENV_UNSUPPORTED,
)
from ..types import HttpVersions


def validate_client_options(
    *,
    cookies: bool,
    max_redirects: int,
    trust_env: bool,
    http_versions: HttpVersions,
) -> None:
    if max_redirects < 0:
        raise ValueError(MAX_REDIRECTS_INVALID)
    if cookies:
        raise NotImplementedError(COOKIES_UNSUPPORTED)
    if trust_env:
        raise NotImplementedError(TRUST_ENV_UNSUPPORTED)
    if http_versions and http_versions != ["HTTP/1.1"]:
        raise NotImplementedError(HTTP_VERSION_UNSUPPORTED)
