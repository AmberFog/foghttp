__all__ = (
    "BLOCKER_AND_WAITER_DEBUG_REQUESTS",
    "CAPPED_DEBUG_REQUEST_COUNT",
    "QUERY_REDACTED_VALUE_ONE",
    "QUERY_REDACTED_VALUE_TWO",
    "SENSITIVE_USERNAME",
    "USERINFO_REDACTED_VALUE",
    "VISIBLE_QUERY_VALUE",
    "ContextBodyError",
    "sensitive_url",
)


BLOCKER_AND_WAITER_DEBUG_REQUESTS = 2
DEBUG_REQUEST_MESSAGE_CAP = 10
CAPPED_DEBUG_REQUEST_COUNT = DEBUG_REQUEST_MESSAGE_CAP + 1
QUERY_REDACTED_VALUE_ONE = "debug-query-value-one"
QUERY_REDACTED_VALUE_TWO = "debug-query-value-two"
USERINFO_REDACTED_VALUE = "debug-userinfo-value"
SENSITIVE_USERNAME = "debug-user"
VISIBLE_QUERY_VALUE = "visible-value"


class ContextBodyError(Exception): ...


def sensitive_url(base_url: str, path: str) -> str:
    scheme, authority = base_url.split("://", maxsplit=1)
    return (
        f"{scheme}://{SENSITIVE_USERNAME}:{USERINFO_REDACTED_VALUE}@{authority}{path}"
        f"?token={QUERY_REDACTED_VALUE_ONE}&api_key={QUERY_REDACTED_VALUE_TWO}&safe={VISIBLE_QUERY_VALUE}"
    )
