__all__ = ("validate_runtime_options",)

from ...messages import (
    RUNTIME_INVALID,
    RUNTIME_WORKERS_ENV_INVALID,
    RUNTIME_WORKERS_INVALID,
    RUNTIME_WORKERS_SHARED_UNSUPPORTED,
)
from .mode import is_valid_runtime, runtime_allows_workers
from .workers import is_valid_runtime_workers, is_valid_runtime_workers_env


def validate_runtime_options(*, runtime: str | None, runtime_workers: int | None) -> None:
    error = _runtime_options_error(runtime=runtime, runtime_workers=runtime_workers)
    if error is not None:
        raise ValueError(error)


def _runtime_options_error(*, runtime: str | None, runtime_workers: int | None) -> str | None:
    if not is_valid_runtime(runtime):
        return RUNTIME_INVALID
    if not is_valid_runtime_workers(runtime_workers):
        return RUNTIME_WORKERS_INVALID
    if runtime_workers is not None and not runtime_allows_workers(runtime):
        return RUNTIME_WORKERS_SHARED_UNSUPPORTED
    if runtime_workers is None and runtime_allows_workers(runtime) and not is_valid_runtime_workers_env():
        return RUNTIME_WORKERS_ENV_INVALID
    return None
