__all__ = (
    "RuntimeMode",
    "is_valid_runtime",
    "runtime_allows_workers",
    "runtime_mode",
    "runtime_workers_env_is_set",
)

import os
from typing import Literal

from .constants import DEDICATED_RUNTIME, RUNTIME_WORKERS_ENV, SHARED_RUNTIME


RuntimeMode = Literal["shared", "dedicated"]


def is_valid_runtime(runtime: str | None) -> bool:
    return runtime in {None, SHARED_RUNTIME, DEDICATED_RUNTIME}


def runtime_allows_workers(runtime: str | None) -> bool:
    return runtime != SHARED_RUNTIME


def runtime_mode(runtime: str | None, runtime_workers: int | None) -> RuntimeMode:
    if runtime == SHARED_RUNTIME:
        return "shared"
    if runtime == DEDICATED_RUNTIME:
        return "dedicated"
    if runtime_workers is not None or runtime_workers_env_is_set():
        return "dedicated"
    return "shared"


def runtime_workers_env_is_set() -> bool:
    return RUNTIME_WORKERS_ENV in os.environ
