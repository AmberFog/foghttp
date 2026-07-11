__all__ = ("current_process_id", "forked_process_error")

from dataclasses import dataclass
import os

from ..errors import LifecycleError


@dataclass(slots=True)
class _ProcessState:
    process_id: int


_PROCESS_STATE = _ProcessState(process_id=os.getpid())


def current_process_id() -> int:
    return _PROCESS_STATE.process_id


def forked_process_error(
    *,
    resource: str,
    created_process_id: int,
    current_process_id: int,
) -> LifecycleError:
    return LifecycleError(
        f"FogHTTP {resource} was created in process {created_process_id} "
        f"and cannot be used in forked process {current_process_id}; "
        "create a new client after fork",
    )


def _refresh_current_process_id() -> None:
    _PROCESS_STATE.process_id = os.getpid()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_refresh_current_process_id)
