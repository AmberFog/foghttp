__all__ = ("is_async_callable",)

from collections.abc import Callable
from inspect import isasyncgenfunction, iscoroutinefunction


def is_async_callable(value: Callable[..., object]) -> bool:
    if iscoroutinefunction(value) or isasyncgenfunction(value):
        return True
    call = type(value).__call__
    return iscoroutinefunction(call) or isasyncgenfunction(call)
