__all__ = ("RetryConditions", "RetryPolicy")

from collections.abc import Collection
from dataclasses import dataclass

from ._validation.numeric import validate_non_negative_int, validate_non_negative_seconds
from .errors import NetworkError


_DEFAULT_RETRY_METHODS = ("GET", "HEAD", "OPTIONS", "QUERY", "TRACE")
_DEFAULT_RETRY_STATUSES = (429, 502, 503, 504)
_HTTP_STATUS_MIN = 100
_HTTP_STATUS_MAX = 599
_METHOD_TOKEN_PUNCTUATION = frozenset("!#$%&'*+-.^_`|~")
_EXCEPTIONS_COLLECTION_ERROR = "RetryConditions.exceptions must be a collection of exception types"
_EXCEPTIONS_UNSUPPORTED_ERROR = "RetryConditions.exceptions currently supports only NetworkError"
_METHODS_COLLECTION_ERROR = "RetryPolicy.methods must be a collection of HTTP method names"
_METHODS_ITEM_ERROR = "RetryPolicy.methods must contain strings"
_METHODS_SYNTAX_ERROR = "RetryPolicy.methods must contain valid HTTP method tokens"
_RETRY_ON_ERROR = "RetryPolicy.retry_on must be RetryConditions"
_STATUSES_COLLECTION_ERROR = "RetryConditions.statuses must be a collection of HTTP status codes"
_STATUSES_ITEM_ERROR = "RetryConditions.statuses must contain integers"
_STATUSES_RANGE_ERROR = "RetryConditions.statuses must contain values between 100 and 599"


@dataclass(frozen=True, init=False, slots=True)
class RetryConditions:
    """Response and exception conditions that can trigger a retry decision."""

    statuses: frozenset[int]
    exceptions: tuple[type[NetworkError], ...]

    def __init__(
        self,
        *,
        statuses: Collection[int] = _DEFAULT_RETRY_STATUSES,
        exceptions: Collection[type[NetworkError]] = (NetworkError,),
    ) -> None:
        object.__setattr__(self, "statuses", _normalize_statuses(statuses))
        object.__setattr__(self, "exceptions", _normalize_exceptions(exceptions))


@dataclass(frozen=True, init=False, slots=True)
class RetryPolicy:
    """Opt-in retry policy applied inside the Rust transport pipeline."""

    retries: int
    backoff: float
    jitter: float
    retry_on: RetryConditions
    methods: frozenset[str]

    def __init__(
        self,
        *,
        retries: int = 2,
        backoff: float = 0.1,
        jitter: float = 0.1,
        retry_on: RetryConditions | None = None,
        methods: Collection[str] = _DEFAULT_RETRY_METHODS,
    ) -> None:
        object.__setattr__(
            self,
            "retries",
            validate_non_negative_int("RetryPolicy.retries", retries),
        )
        object.__setattr__(
            self,
            "backoff",
            validate_non_negative_seconds("RetryPolicy.backoff", backoff),
        )
        object.__setattr__(
            self,
            "jitter",
            validate_non_negative_seconds("RetryPolicy.jitter", jitter),
        )
        object.__setattr__(
            self,
            "retry_on",
            RetryConditions() if retry_on is None else _validate_retry_conditions(retry_on),
        )
        object.__setattr__(self, "methods", _normalize_methods(methods))


def _normalize_statuses(statuses: Collection[int]) -> frozenset[int]:
    if isinstance(statuses, str | bytes) or not isinstance(statuses, Collection):
        raise TypeError(_STATUSES_COLLECTION_ERROR)

    normalized: set[int] = set()
    for status in statuses:
        if isinstance(status, bool) or not isinstance(status, int):
            raise TypeError(_STATUSES_ITEM_ERROR)
        if not _HTTP_STATUS_MIN <= status <= _HTTP_STATUS_MAX:
            raise ValueError(_STATUSES_RANGE_ERROR)
        normalized.add(status)
    return frozenset(normalized)


def _normalize_exceptions(
    exceptions: Collection[type[NetworkError]],
) -> tuple[type[NetworkError], ...]:
    if isinstance(exceptions, type) or not isinstance(exceptions, Collection):
        raise TypeError(_EXCEPTIONS_COLLECTION_ERROR)

    normalized: list[type[NetworkError]] = []
    for exception in exceptions:
        if exception is not NetworkError:
            raise ValueError(_EXCEPTIONS_UNSUPPORTED_ERROR)
        if exception not in normalized:
            normalized.append(exception)
    return tuple(normalized)


def _validate_retry_conditions(retry_on: RetryConditions) -> RetryConditions:
    if not isinstance(retry_on, RetryConditions):
        raise TypeError(_RETRY_ON_ERROR)
    return retry_on


def _normalize_methods(methods: Collection[str]) -> frozenset[str]:
    if isinstance(methods, str | bytes) or not isinstance(methods, Collection):
        raise TypeError(_METHODS_COLLECTION_ERROR)

    normalized: set[str] = set()
    for method in methods:
        if not isinstance(method, str):
            raise TypeError(_METHODS_ITEM_ERROR)
        if not method or not all(_is_method_token_character(character) for character in method):
            raise ValueError(_METHODS_SYNTAX_ERROR)
        normalized.add(method.upper())
    return frozenset(normalized)


def _is_method_token_character(character: str) -> bool:
    return character.isascii() and (character.isalnum() or character in _METHOD_TOKEN_PUNCTUATION)
