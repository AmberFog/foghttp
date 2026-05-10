__all__ = (
    "BenchmarkArgs",
    "ClientConfig",
    "ClientSpec",
    "LoadResult",
    "ResponseOutcome",
    "RunResult",
    "Scenario",
)

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from bench.clients.base import AsyncClientAdapter, SyncClientAdapter


@dataclass(frozen=True)
class BenchmarkArgs:
    clients: str
    modes: str
    concurrency: str
    requests: int
    warmup: int
    repeats: int
    max_redirects: int
    seed: int
    no_shuffle: bool
    output_dir: str
    scenarios: str


@dataclass(frozen=True)
class ClientConfig:
    concurrency: int
    max_connections: int
    follow_redirects: bool
    max_redirects: int


@dataclass(frozen=True)
class ClientSpec:
    name: str
    mode: str
    factory: Callable[[ClientConfig], "AsyncClientAdapter | SyncClientAdapter"]


@dataclass(frozen=True)
class Scenario:
    name: str
    method: str
    path: str
    body: bytes | None = None
    json_body: dict[str, Any] | None = None
    expected_status: int = 200
    expected_json_keys: tuple[str, ...] = ()
    expected_content_length: int | None = None
    expected_redirects: int | None = None
    expected_final_path: str | None = None
    follow_redirects: bool = False
    max_connections: int | None = None
    description: str = ""


@dataclass(frozen=True)
class ResponseOutcome:
    status_code: int
    json_ok: bool = True
    content_length: int | None = None
    history_count: int | None = None
    final_url: str | None = None


@dataclass(frozen=True)
class LoadResult:
    latencies_ms: list[float]
    errors: int
    error_types: dict[str, int]


@dataclass
class RunResult:
    client: str
    mode: str
    scenario: str
    concurrency: int
    max_connections: int
    requests: int
    repeat: int
    duration_s: float
    requests_per_second: float
    ok_requests_per_second: float
    ok_requests: int
    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    errors: int
    warmup_errors: int
    error_types: dict[str, int]
    warmup_error_types: dict[str, int]
    process_cpu_s: float
    peak_rss_mb: float | None
    peak_threads: int | None
    peak_fds: int | None
    client_stats: dict[str, Any] | None
