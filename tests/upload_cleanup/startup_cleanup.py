from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from .constants import COMPLETION_WATCHDOG


if TYPE_CHECKING:
    from concurrent.futures import Future

    from foghttp._upload_body.cleanup_owner import CleanupOwner


def admitted_completions(owner: CleanupOwner) -> tuple[Future[None], ...]:
    with owner.state.condition:
        return tuple(reservation.completion for reservation in owner.state.reservations)


def wait_for_cleanup(owner: CleanupOwner) -> None:
    for completion in admitted_completions(owner):
        completion.result(timeout=COMPLETION_WATCHDOG)


async def wait_for_async_cleanup(owner: CleanupOwner) -> None:
    completions = admitted_completions(owner)
    if completions:
        await asyncio.wait_for(
            asyncio.gather(*(asyncio.wrap_future(completion) for completion in completions)),
            COMPLETION_WATCHDOG,
        )
