from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import Coroutine


def cancel_before_first_step(
    loop: asyncio.AbstractEventLoop,
    coroutine: Coroutine[Any, Any, object],
    **kwargs: Any,
) -> asyncio.Task[object]:
    task = asyncio.Task(coroutine, loop=loop, **kwargs)
    task.cancel()
    return task
