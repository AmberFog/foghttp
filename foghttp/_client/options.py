__all__ = ("validate_client_options",)

from ..messages import (
    COOKIES_UNSUPPORTED,
    HTTP_VERSION_UNSUPPORTED,
    MAX_REDIRECTS_INVALID,
    RUNTIME_WORKERS_ENV_INVALID,
    RUNTIME_WORKERS_INVALID,
    TRUST_ENV_UNSUPPORTED,
)
from ..types import HttpVersions
from .runtime.workers import is_valid_runtime_workers, is_valid_runtime_workers_env


def validate_client_options(
    *,
    cookies: bool,
    max_redirects: int,
    runtime_workers: int | None,
    trust_env: bool,
    http_versions: HttpVersions,
) -> None:
    if max_redirects < 0:
        raise ValueError(MAX_REDIRECTS_INVALID)
    if not is_valid_runtime_workers(runtime_workers):
        raise ValueError(RUNTIME_WORKERS_INVALID)
    if runtime_workers is None and not is_valid_runtime_workers_env():
        raise ValueError(RUNTIME_WORKERS_ENV_INVALID)
    if cookies:
        raise NotImplementedError(COOKIES_UNSUPPORTED)
    if trust_env:
        raise NotImplementedError(TRUST_ENV_UNSUPPORTED)
    if http_versions and http_versions != ["HTTP/1.1"]:
        raise NotImplementedError(HTTP_VERSION_UNSUPPORTED)
