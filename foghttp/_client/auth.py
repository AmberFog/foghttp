__all__ = ("AuthConfig", "normalize_auth")

from base64 import b64encode
from dataclasses import dataclass, field
from inspect import isawaitable, iscoroutine
from typing import cast

from .._validation.callables import is_async_callable
from ..auth import Auth, AuthHook
from ..headers import Headers, HeaderSource
from .request_builder.header_policy import validate_safe_request_headers


_AUTH_CONFIGURATION_ERROR = "auth must be a (username, password) tuple or a synchronous callable"
_BASIC_CREDENTIALS_ERROR = "auth basic credentials must contain exactly two strings"
_AUTH_HOOK_RETURN_ERROR = "auth hook must return HTTP headers or None"
_AUTH_HOOK_SYNC_ERROR = "auth hook must be synchronous"
_AUTH_USERNAME_COLON_ERROR = "auth username must not contain ':'"
_BASIC_CREDENTIALS_SIZE = 2


@dataclass(frozen=True, repr=False, slots=True)
class AuthConfig:
    basic_authorization: str | None = field(default=None, repr=False)
    hook: AuthHook | None = field(default=None, repr=False)


def normalize_auth(auth: Auth) -> AuthConfig | None:
    if auth is None:
        return None
    if isinstance(auth, tuple):
        return AuthConfig(basic_authorization=_basic_authorization(auth))
    if not callable(auth):
        raise TypeError(_AUTH_CONFIGURATION_ERROR)
    _validate_sync_hook(auth)
    return AuthConfig(hook=auth)


def _basic_authorization(credentials: tuple[object, ...]) -> str:
    if len(credentials) != _BASIC_CREDENTIALS_SIZE:
        raise TypeError(_BASIC_CREDENTIALS_ERROR)
    if not all(isinstance(value, str) for value in credentials):
        raise TypeError(_BASIC_CREDENTIALS_ERROR)
    username, password = cast("tuple[str, str]", credentials)
    if ":" in username:
        raise ValueError(_AUTH_USERNAME_COLON_ERROR)
    token = b64encode(f"{username}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


def _validate_sync_hook(hook: AuthHook) -> None:
    if is_async_callable(hook):
        raise TypeError(_AUTH_HOOK_SYNC_ERROR)


def _normalize_auth_header_pairs(source: object) -> list[tuple[str, str]]:
    if isawaitable(source):
        if iscoroutine(source):
            source.close()
        raise TypeError(_AUTH_HOOK_RETURN_ERROR)
    try:
        headers = Headers(cast("HeaderSource", source))
    except (AttributeError, TypeError, ValueError) as error:
        raise TypeError(_AUTH_HOOK_RETURN_ERROR) from error
    pairs = headers.multi_items()
    for name, value in pairs:
        if not isinstance(name, str) or not isinstance(value, str):
            raise TypeError(_AUTH_HOOK_RETURN_ERROR)
    validate_safe_request_headers(headers)
    return pairs
