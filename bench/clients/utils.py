__all__ = (
    "json_has_keys",
    "request_kwargs",
    "response_content",
    "response_outcome",
    "stats_from_client",
)

from dataclasses import asdict
from typing import Any

from bench.models import ResponseOutcome, Scenario


def request_kwargs(scenario: Scenario, *, body_key: str) -> dict[str, Any]:
    if scenario.json_body is not None:
        return {"json": scenario.json_body}
    if scenario.body is not None:
        return {body_key: scenario.body}
    return {}


def response_outcome(
    *,
    response: Any,
    scenario: Scenario,
    status_code: int,
    history_count: int | None = None,
    final_url: str | None = None,
) -> ResponseOutcome:
    json_ok = True
    if scenario.expected_json_keys:
        json_ok = json_has_keys(read_response_json(response), scenario.expected_json_keys)

    content_length = None
    if scenario.expected_content_length is not None:
        content = response_content(response)
        content_length = len(content) if isinstance(content, bytes | bytearray) else None

    return ResponseOutcome(
        status_code=status_code,
        json_ok=json_ok,
        content_length=content_length,
        history_count=history_count,
        final_url=final_url,
    )


def read_response_json(response: Any) -> Any:
    reader = response.json
    return reader() if callable(reader) else reader


def response_content(response: Any) -> bytes | bytearray | None:
    reader = getattr(response, "read", None)
    if callable(reader):
        content = reader()
        if isinstance(content, bytes | bytearray):
            return content

    content = getattr(response, "content", None)
    return content if isinstance(content, bytes | bytearray) else None


def json_has_keys(value: Any, keys: tuple[str, ...]) -> bool:
    return isinstance(value, dict) and all(key in value for key in keys)


def stats_from_client(client: Any) -> dict[str, Any] | None:
    stats = client.stats()
    if hasattr(stats, "__dataclass_fields__"):
        return asdict(stats)
    return dict(stats)
