__all__ = ("is_valid_runtime_workers", "is_valid_runtime_workers_env")

import os

from .constants import MAX_RUNTIME_WORKERS, RUNTIME_WORKERS_ENV


def is_valid_runtime_workers(runtime_workers: int | None) -> bool:
    if runtime_workers is None:
        return True
    if isinstance(runtime_workers, bool) or not isinstance(runtime_workers, int):
        return False
    return 1 <= runtime_workers <= MAX_RUNTIME_WORKERS


def is_valid_runtime_workers_env() -> bool:
    value = os.environ.get(RUNTIME_WORKERS_ENV)
    if value is None:
        return True
    if not value.isascii() or not value.isdecimal():
        return False
    runtime_workers = int(value)
    return 1 <= runtime_workers <= MAX_RUNTIME_WORKERS
