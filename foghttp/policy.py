__all__ = (
    "TransportPolicyBodyState",
    "TransportPolicyHooks",
    "TransportPolicyRequest",
    "TransportPolicyResponse",
)

from collections.abc import Callable
from dataclasses import dataclass, field
from inspect import isasyncgenfunction, iscoroutinefunction
from typing import Literal, TypeAlias

from ._redaction import redact_url


TransportPolicyBodyState: TypeAlias = Literal[
    "empty",
    "replayable",
    "non_replayable",
]


@dataclass(frozen=True, repr=False, slots=True)
class TransportPolicyRequest:
    """Immutable request snapshot passed to an enabled transport policy hook."""

    method: str
    url: str
    body: TransportPolicyBodyState
    redirect_hop: int

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        method = self.method
        url = redact_url(self.url)
        body = self.body
        redirect_hop = self.redirect_hop
        return f"{class_name}(method={method!r}, url={url!r}, body={body!r}, redirect_hop={redirect_hop!r})"


@dataclass(frozen=True, repr=False, slots=True)
class TransportPolicyResponse:
    """Immutable response-head snapshot passed to an enabled policy hook."""

    request: TransportPolicyRequest
    status_code: int
    headers: tuple[tuple[str, str], ...]

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        request = self.request
        status_code = self.status_code
        header_count = len(self.headers)
        return f"{class_name}(request={request!r}, status_code={status_code!r}, headers=<{header_count} headers>)"


@dataclass(frozen=True, slots=True)
class TransportPolicyHooks:
    """Opt-in synchronous transport policy observers.

    Hooks may reject a request by raising an exception. They must return
    ``None`` and cannot mutate requests, responses, or transport resources.
    """

    before_send: Callable[[TransportPolicyRequest], None] | None = field(default=None, repr=False)
    on_response_headers: Callable[[TransportPolicyResponse], None] | None = field(default=None, repr=False)
    after_response_body: Callable[[TransportPolicyResponse], None] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _validate_hook("before_send", self.before_send)
        _validate_hook("on_response_headers", self.on_response_headers)
        _validate_hook("after_response_body", self.after_response_body)

    @property
    def enabled(self) -> bool:
        return any(
            hook is not None
            for hook in (
                self.before_send,
                self.on_response_headers,
                self.after_response_body,
            )
        )


def _validate_hook(name: str, hook: object | None) -> None:
    if hook is None:
        return
    if not callable(hook):
        message = f"{name} transport policy hook must be callable or None"
        raise TypeError(message)
    hook_call = type(hook).__call__
    if (
        iscoroutinefunction(hook)
        or isasyncgenfunction(hook)
        or iscoroutinefunction(hook_call)
        or isasyncgenfunction(hook_call)
    ):
        message = f"{name} transport policy hook must be synchronous"
        raise TypeError(message)
