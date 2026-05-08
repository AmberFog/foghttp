from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
import gc
import importlib
from importlib import metadata
import json
from pathlib import Path
import platform
from queue import Empty, Queue
import random
import resource
import statistics
import sys
import time
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import Callable


__all__ = ("main",)


ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "bench" / "results"
ASYNC_MODE = "async"
SYNC_MODE = "sync"
DEFAULT_CLIENTS = "foghttp,httpx,zapros"
DEFAULT_MODES = ASYNC_MODE
DEFAULT_SCENARIOS = (
    "json-small,"
    "json-decode-small,"
    "bytes-64k,"
    "post-json-echo,"
    "post-echo-64k,"
    "redirect-get-302,"
    "redirect-head-302,"
    "redirect-post-303,"
    "redirect-post-307,"
    "delay-20ms,"
    "pool-contention-20ms"
)
DEFAULT_MAX_REDIRECTS = 20
POOL_CONTENTION_CONNECTIONS = 10
BENCHMARK_SEED = 20260507
MIN_REDIRECT_PATH_PARTS = 2
MIN_VARIATION_SAMPLES = 2
MAX_SPLIT_ONCE = 1

HTTP_REASONS = {
    200: "OK",
    301: "Moved Permanently",
    302: "Found",
    303: "See Other",
    307: "Temporary Redirect",
    308: "Permanent Redirect",
    404: "Not Found",
}


def build_post_json() -> dict[str, Any]:
    try:
        faker_module = importlib.import_module("faker")
    except ImportError:
        return {
            "name": "Ada Lovelace",
            "file_name": "benchmark.json",
            "email": "ada@example.test",
            "tags": ["foghttp", "benchmark", "json"],
            "active": True,
        }

    faker = faker_module.Faker()
    faker.seed_instance(BENCHMARK_SEED)
    return {
        "name": faker.name(),
        "file_name": faker.file_name(extension="json"),
        "email": faker.email(),
        "tags": [faker.word() for _ in range(3)],
        "active": True,
    }


POST_JSON = build_post_json()
SMALL_JSON_OBJECT = {
    "ok": True,
    "message": "foghttp benchmark",
    "items": [1, 2, 3, 4],
    "meta": {
        "client": "local",
        "shape": "small-json",
    },
}
SMALL_JSON = json.dumps(SMALL_JSON_OBJECT, separators=(",", ":")).encode()
BYTES_64K = b"x" * 65536
ECHO_64K = b"y" * 65536
REDIRECT_BODY = b"redirect-body"


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
    factory: Callable[[ClientConfig], AsyncClientAdapter | SyncClientAdapter]


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


class AsyncClientAdapter:
    async def request(self, scenario: Scenario, url: str) -> ResponseOutcome:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    def stats(self) -> dict[str, Any] | None:
        return None


class SyncClientAdapter:
    def request(self, scenario: Scenario, url: str) -> ResponseOutcome:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def stats(self) -> dict[str, Any] | None:
        return None


class FogHTTPAsyncAdapter(AsyncClientAdapter):
    def __init__(self, client: Any) -> None:
        self.client = client

    async def request(self, scenario: Scenario, url: str) -> ResponseOutcome:
        response = await self.client.request(
            scenario.method,
            url,
            **request_kwargs(scenario, body_key="content"),
        )
        return response_outcome(
            response=response,
            scenario=scenario,
            status_code=int(response.status_code),
            history_count=len(response.history),
            final_url=response.url,
        )

    async def close(self) -> None:
        await self.client.aclose()

    def stats(self) -> dict[str, Any] | None:
        return stats_from_client(self.client)


class FogHTTPSyncAdapter(SyncClientAdapter):
    def __init__(self, client: Any) -> None:
        self.client = client

    def request(self, scenario: Scenario, url: str) -> ResponseOutcome:
        response = self.client.request(
            scenario.method,
            url,
            **request_kwargs(scenario, body_key="content"),
        )
        return response_outcome(
            response=response,
            scenario=scenario,
            status_code=int(response.status_code),
            history_count=len(response.history),
            final_url=response.url,
        )

    def close(self) -> None:
        self.client.close()

    def stats(self) -> dict[str, Any] | None:
        return stats_from_client(self.client)


class HTTPXAsyncAdapter(AsyncClientAdapter):
    def __init__(self, client: Any) -> None:
        self.client = client

    async def request(self, scenario: Scenario, url: str) -> ResponseOutcome:
        response = await self.client.request(
            scenario.method,
            url,
            **request_kwargs(scenario, body_key="content"),
        )
        return response_outcome(
            response=response,
            scenario=scenario,
            status_code=int(response.status_code),
            history_count=len(response.history),
            final_url=str(response.url),
        )

    async def close(self) -> None:
        await self.client.aclose()


class HTTPXSyncAdapter(SyncClientAdapter):
    def __init__(self, client: Any) -> None:
        self.client = client

    def request(self, scenario: Scenario, url: str) -> ResponseOutcome:
        response = self.client.request(
            scenario.method,
            url,
            **request_kwargs(scenario, body_key="content"),
        )
        return response_outcome(
            response=response,
            scenario=scenario,
            status_code=int(response.status_code),
            history_count=len(response.history),
            final_url=str(response.url),
        )

    def close(self) -> None:
        self.client.close()


class ZaprosAsyncAdapter(AsyncClientAdapter):
    def __init__(self, client: Any) -> None:
        self.client = client

    async def request(self, scenario: Scenario, url: str) -> ResponseOutcome:
        response = await self.client.request(
            scenario.method,
            url,
            **request_kwargs(scenario, body_key="body"),
        )
        return response_outcome(
            response=response,
            scenario=scenario,
            status_code=int(response.status),
        )

    async def close(self) -> None:
        await self.client.aclose()


class ZaprosSyncAdapter(SyncClientAdapter):
    def __init__(self, client: Any) -> None:
        self.client = client

    def request(self, scenario: Scenario, url: str) -> ResponseOutcome:
        response = self.client.request(
            scenario.method,
            url,
            **request_kwargs(scenario, body_key="body"),
        )
        return response_outcome(
            response=response,
            scenario=scenario,
            status_code=int(response.status),
        )

    def close(self) -> None:
        self.client.close()


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


def outcome_matches(scenario: Scenario, outcome: ResponseOutcome) -> bool:
    if outcome.status_code != scenario.expected_status:
        return False
    if not outcome.json_ok:
        return False
    if scenario.expected_content_length is not None and outcome.content_length != scenario.expected_content_length:
        return False
    if (
        scenario.expected_redirects is not None
        and outcome.history_count is not None
        and outcome.history_count != scenario.expected_redirects
    ):
        return False
    if scenario.expected_final_path is None or outcome.final_url is None:
        return True
    return outcome.final_url.endswith(scenario.expected_final_path)


class ResourceSampler:
    def __init__(self, interval: float = 0.02) -> None:
        self.interval = interval
        self.peak_rss_mb: float | None = None
        self.peak_threads: int | None = None
        self.peak_fds: int | None = None
        self._process: Any | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def __aenter__(self) -> ResourceSampler:
        try:
            psutil = importlib.import_module("psutil")
        except ImportError:
            self._process = None
        else:
            self._process = psutil.Process()
        self._running = True
        self._task = asyncio.create_task(self._sample_loop())
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self._running = False
        if self._task is not None:
            await self._task
        if self.peak_rss_mb is None:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            scale = 1024 * 1024 if sys.platform == "darwin" else 1024
            self.peak_rss_mb = usage.ru_maxrss / scale

    async def _sample_loop(self) -> None:
        while self._running:
            self.sample()
            await asyncio.sleep(self.interval)
        self.sample()

    def sample(self) -> None:
        if self._process is None:
            return
        rss_mb = self._process.memory_info().rss / 1024 / 1024
        threads = self._process.num_threads()
        fds_getter = getattr(self._process, "num_fds", None)
        fds = fds_getter() if fds_getter is not None else None
        self.peak_rss_mb = max(self.peak_rss_mb or 0.0, rss_mb)
        self.peak_threads = max(self.peak_threads or 0, threads)
        if fds is not None:
            self.peak_fds = max(self.peak_fds or 0, fds)


async def handle_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    keep_alive = True
    try:
        while keep_alive:
            try:
                header_block = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
                break

            first_line, headers = parse_request_headers(header_block)
            if not first_line:
                break

            try:
                method, path, _version = first_line.split(" ", 2)
            except ValueError:
                break

            content_length = int(headers.get("content-length", "0"))
            body = await reader.readexactly(content_length) if content_length else b""
            keep_alive = headers.get("connection", "").lower() != "close"

            delay_ms = delay_from_path(path)
            if delay_ms is not None:
                await asyncio.sleep(delay_ms / 1000)

            status_code, response_body, content_type, extra_headers = build_response(path, body)
            await write_response(
                writer,
                method=method,
                status_code=status_code,
                body=response_body,
                content_type=content_type,
                keep_alive=keep_alive,
                extra_headers=extra_headers,
            )
    finally:
        writer.close()
        await writer.wait_closed()


def parse_request_headers(header_block: bytes) -> tuple[str, dict[str, str]]:
    lines = header_block.decode("latin1").split("\r\n")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return lines[0], headers


def build_response(path: str, body: bytes) -> tuple[int, bytes, bytes, dict[str, str]]:
    request_path = path.split("?", MAX_SPLIT_ONCE)[0]
    redirect = redirect_response(request_path)
    if redirect is not None:
        return redirect
    if request_path == "/json-small":
        return 200, SMALL_JSON, b"application/json", {}
    if request_path == "/bytes-64k":
        return 200, BYTES_64K, b"application/octet-stream", {}
    if request_path == "/echo":
        return 200, body, b"application/octet-stream", {}
    if request_path.startswith("/delay/"):
        return (
            200,
            SMALL_JSON,
            b"application/json",
            {"x-benchmark-delay-ms": request_path.rsplit("/", MAX_SPLIT_ONCE)[1]},
        )
    return 404, b"not found", b"text/plain", {}


def delay_from_path(path: str) -> int | None:
    request_path = path.split("?", MAX_SPLIT_ONCE)[0]
    if not request_path.startswith("/delay/"):
        return None
    return int(request_path.rsplit("/", MAX_SPLIT_ONCE)[1])


def redirect_response(path: str) -> tuple[int, bytes, bytes, dict[str, str]] | None:
    parts = path.strip("/").split("/")
    if len(parts) < MIN_REDIRECT_PATH_PARTS or parts[0] != "redirect":
        return None

    status_code = int(parts[1])
    target = "/" + "/".join(parts[MIN_REDIRECT_PATH_PARTS:]) if len(parts) > MIN_REDIRECT_PATH_PARTS else "/json-small"
    return status_code, b"", b"text/plain", {"location": target}


async def write_response(
    writer: asyncio.StreamWriter,
    *,
    method: str,
    status_code: int,
    body: bytes,
    content_type: bytes,
    keep_alive: bool,
    extra_headers: dict[str, str],
) -> None:
    response_body = b"" if method == "HEAD" else body
    reason = HTTP_REASONS.get(status_code, "OK")
    headers = [
        f"HTTP/1.1 {status_code} {reason}",
        f"content-length: {len(body)}",
        f"content-type: {content_type.decode()}",
        f"connection: {'keep-alive' if keep_alive else 'close'}",
    ]
    headers.extend(f"{name}: {value}" for name, value in extra_headers.items())
    writer.write("\r\n".join(headers).encode() + b"\r\n\r\n" + response_body)
    await writer.drain()


@asynccontextmanager
async def benchmark_server() -> Any:
    server = await asyncio.start_server(handle_connection, "127.0.0.1", 0)
    sockets = server.sockets or []
    if not sockets:
        msg = "benchmark server did not bind a socket"
        raise RuntimeError(msg)
    host, port = sockets[0].getsockname()[:2]
    async with server:
        yield f"http://{host}:{port}"


def make_foghttp_async(config: ClientConfig) -> AsyncClientAdapter:
    foghttp = importlib.import_module("foghttp")
    limits = foghttp_limits(foghttp, config)
    timeouts = foghttp.Timeouts(connect=2.0, read=10.0, write=10.0, pool=5.0, total=30.0)
    client = foghttp.AsyncClient(
        limits=limits,
        timeouts=timeouts,
        follow_redirects=config.follow_redirects,
        max_redirects=config.max_redirects,
    )
    return FogHTTPAsyncAdapter(client)


def make_foghttp_sync(config: ClientConfig) -> SyncClientAdapter:
    foghttp = importlib.import_module("foghttp")
    limits = foghttp_limits(foghttp, config)
    timeouts = foghttp.Timeouts(connect=2.0, read=10.0, write=10.0, pool=5.0, total=30.0)
    client = foghttp.Client(
        limits=limits,
        timeouts=timeouts,
        follow_redirects=config.follow_redirects,
        max_redirects=config.max_redirects,
    )
    return FogHTTPSyncAdapter(client)


def foghttp_limits(foghttp: Any, config: ClientConfig) -> Any:
    return foghttp.Limits(
        max_connections=config.max_connections,
        max_connections_per_host=config.max_connections,
        max_pending_acquires=max(config.max_connections * 10, config.concurrency),
    )


def make_httpx_async(config: ClientConfig) -> AsyncClientAdapter:
    httpx = importlib.import_module("httpx")
    limits = httpx.Limits(
        max_connections=config.max_connections,
        max_keepalive_connections=config.max_connections,
    )
    timeout = httpx.Timeout(connect=2.0, read=10.0, write=10.0, pool=5.0)
    client = httpx.AsyncClient(
        limits=limits,
        timeout=timeout,
        trust_env=False,
        follow_redirects=config.follow_redirects,
        max_redirects=config.max_redirects,
    )
    return HTTPXAsyncAdapter(client)


def make_httpx_sync(config: ClientConfig) -> SyncClientAdapter:
    httpx = importlib.import_module("httpx")
    limits = httpx.Limits(
        max_connections=config.max_connections,
        max_keepalive_connections=config.max_connections,
    )
    timeout = httpx.Timeout(connect=2.0, read=10.0, write=10.0, pool=5.0)
    client = httpx.Client(
        limits=limits,
        timeout=timeout,
        trust_env=False,
        follow_redirects=config.follow_redirects,
        max_redirects=config.max_redirects,
    )
    return HTTPXSyncAdapter(client)


def make_zapros_async(config: ClientConfig) -> AsyncClientAdapter:
    zapros = importlib.import_module("zapros")
    handler = zapros.AsyncStdNetworkHandler(
        total_timeout=30.0,
        connect_timeout=2.0,
        read_timeout=10.0,
        write_timeout=10.0,
        max_connections_per_host=config.max_connections,
        max_idle_connections_per_host=config.max_connections,
    )
    if config.follow_redirects:
        handler = zapros.RedirectMiddleware(handler, max_redirects=config.max_redirects)
    return ZaprosAsyncAdapter(zapros.AsyncClient(handler=handler))


def make_zapros_sync(config: ClientConfig) -> SyncClientAdapter:
    zapros = importlib.import_module("zapros")
    handler = zapros.StdNetworkHandler(
        total_timeout=30.0,
        connect_timeout=2.0,
        read_timeout=10.0,
        write_timeout=10.0,
        max_connections_per_host=config.max_connections,
        max_idle_connections_per_host=config.max_connections,
    )
    if config.follow_redirects:
        handler = zapros.RedirectMiddleware(handler, max_redirects=config.max_redirects)
    return ZaprosSyncAdapter(zapros.Client(handler=handler))


def available_clients(
    requested_clients: list[str],
    requested_modes: list[str],
) -> tuple[list[ClientSpec], dict[str, str]]:
    factories = {
        ASYNC_MODE: {
            "foghttp": make_foghttp_async,
            "httpx": make_httpx_async,
            "zapros": make_zapros_async,
        },
        SYNC_MODE: {
            "foghttp": make_foghttp_sync,
            "httpx": make_httpx_sync,
            "zapros": make_zapros_sync,
        },
    }
    clients: list[ClientSpec] = []
    skipped: dict[str, str] = {}
    for mode in requested_modes:
        mode_factories = factories.get(mode)
        if mode_factories is None:
            skipped[f"{mode}:*"] = "unknown mode"
            continue
        for name in requested_clients:
            factory = mode_factories.get(name)
            if factory is None:
                skipped[f"{mode}:{name}"] = "unknown client"
                continue
            module_name = "foghttp" if name == "foghttp" else name
            try:
                importlib.import_module(module_name)
            except Exception as exc:  # noqa: BLE001
                skipped[f"{mode}:{name}"] = f"{type(exc).__name__}: {exc}"
                continue
            clients.append(ClientSpec(name=name, mode=mode, factory=factory))
    return clients, skipped


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, round((pct / 100) * (len(values) - 1))))
    return values[index]


async def run_once(
    *,
    spec: ClientSpec,
    base_url: str,
    scenario: Scenario,
    concurrency: int,
    requests: int,
    repeat: int,
    warmup: int,
    max_redirects: int,
) -> RunResult:
    max_connections = scenario.max_connections or concurrency
    config = ClientConfig(
        concurrency=concurrency,
        max_connections=max_connections,
        follow_redirects=scenario.follow_redirects,
        max_redirects=max_redirects,
    )
    client = spec.factory(config)
    url = base_url + scenario.path

    try:
        warmup_result = await run_load(client, scenario, url, concurrency, warmup, collect=False)
        gc.collect()
        cpu_start = time.process_time()
        started = time.perf_counter()
        async with ResourceSampler() as sampler:
            load_result = await run_load(client, scenario, url, concurrency, requests, collect=True)
        duration = time.perf_counter() - started
        cpu = time.process_time() - cpu_start
        latencies = sorted(load_result.latencies_ms)
        client_stats = client.stats()
    finally:
        close_result = client.close()
        if hasattr(close_result, "__await__"):
            await close_result

    ok_requests = requests - load_result.errors
    return RunResult(
        client=spec.name,
        mode=spec.mode,
        scenario=scenario.name,
        concurrency=concurrency,
        max_connections=max_connections,
        requests=requests,
        repeat=repeat,
        duration_s=duration,
        requests_per_second=requests / duration if duration > 0 else 0.0,
        ok_requests_per_second=ok_requests / duration if duration > 0 else 0.0,
        ok_requests=ok_requests,
        p50_ms=percentile(latencies, 50),
        p90_ms=percentile(latencies, 90),
        p95_ms=percentile(latencies, 95),
        p99_ms=percentile(latencies, 99),
        min_ms=latencies[0] if latencies else 0.0,
        max_ms=latencies[-1] if latencies else 0.0,
        errors=load_result.errors,
        warmup_errors=warmup_result.errors,
        error_types=load_result.error_types,
        warmup_error_types=warmup_result.error_types,
        process_cpu_s=cpu,
        peak_rss_mb=sampler.peak_rss_mb,
        peak_threads=sampler.peak_threads,
        peak_fds=sampler.peak_fds,
        client_stats=client_stats,
    )


async def run_load(
    client: AsyncClientAdapter | SyncClientAdapter,
    scenario: Scenario,
    url: str,
    concurrency: int,
    requests: int,
    *,
    collect: bool,
) -> LoadResult:
    if isinstance(client, AsyncClientAdapter):
        return await run_async_load(client, scenario, url, concurrency, requests, collect=collect)
    return await asyncio.to_thread(run_sync_load, client, scenario, url, concurrency, requests, collect=collect)


async def run_async_load(
    client: AsyncClientAdapter,
    scenario: Scenario,
    url: str,
    concurrency: int,
    requests: int,
    *,
    collect: bool,
) -> LoadResult:
    queue: asyncio.Queue[int] = asyncio.Queue()
    for index in range(requests):
        queue.put_nowait(index)

    async def worker() -> LoadResult:
        latencies: list[float] = []
        error_types: dict[str, int] = {}
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return LoadResult(latencies, sum(error_types.values()), error_types)

            started = time.perf_counter_ns()
            try:
                outcome = await client.request(scenario, url)
                if not outcome_matches(scenario, outcome):
                    increment(error_types, "check_failed")
            except Exception as exc:  # noqa: BLE001
                increment(error_types, type(exc).__name__)
            finally:
                if collect:
                    latencies.append((time.perf_counter_ns() - started) / 1_000_000)
                queue.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(min(concurrency, requests))]
    await queue.join()
    results = await asyncio.gather(*workers)
    return merge_load_results(results)


def run_sync_load(
    client: SyncClientAdapter,
    scenario: Scenario,
    url: str,
    concurrency: int,
    requests: int,
    *,
    collect: bool,
) -> LoadResult:
    queue: Queue[int] = Queue()
    for index in range(requests):
        queue.put_nowait(index)

    def worker() -> LoadResult:
        latencies: list[float] = []
        error_types: dict[str, int] = {}
        while True:
            try:
                queue.get_nowait()
            except Empty:
                return LoadResult(latencies, sum(error_types.values()), error_types)

            started = time.perf_counter_ns()
            try:
                outcome = client.request(scenario, url)
                if not outcome_matches(scenario, outcome):
                    increment(error_types, "check_failed")
            except Exception as exc:  # noqa: BLE001
                increment(error_types, type(exc).__name__)
            finally:
                if collect:
                    latencies.append((time.perf_counter_ns() - started) / 1_000_000)
                queue.task_done()

    with ThreadPoolExecutor(max_workers=min(concurrency, requests)) as executor:
        results = list(executor.map(lambda _index: worker(), range(min(concurrency, requests))))
    return merge_load_results(results)


def increment(values: dict[str, int], key: str) -> None:
    values[key] = values.get(key, 0) + 1


def merge_load_results(results: list[LoadResult]) -> LoadResult:
    latencies: list[float] = []
    error_types: dict[str, int] = {}
    for result in results:
        latencies.extend(result.latencies_ms)
        for key, count in result.error_types.items():
            error_types[key] = error_types.get(key, 0) + count
    return LoadResult(latencies, sum(error_types.values()), error_types)


def aggregate_results(results: list[RunResult]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, int, int], list[RunResult]] = {}
    for result in results:
        key = (result.mode, result.client, result.scenario, result.concurrency, result.max_connections)
        grouped.setdefault(key, []).append(result)

    rows: list[dict[str, Any]] = []
    for (mode, client, scenario, concurrency, max_connections), items in sorted(grouped.items()):
        requests_total = sum(item.requests for item in items)
        errors_total = sum(item.errors for item in items)
        rows.append(
            {
                "mode": mode,
                "client": client,
                "scenario": scenario,
                "concurrency": concurrency,
                "max_connections": max_connections,
                "requests": items[0].requests,
                "repeats": len(items),
                "req_s_median": statistics.median(item.requests_per_second for item in items),
                "ok_req_s_median": statistics.median(item.ok_requests_per_second for item in items),
                "req_s_cv_percent": coefficient_of_variation(
                    [item.requests_per_second for item in items],
                ),
                "p50_ms_median": statistics.median(item.p50_ms for item in items),
                "p95_ms_median": statistics.median(item.p95_ms for item in items),
                "p99_ms_median": statistics.median(item.p99_ms for item in items),
                "rss_mb_max": max((item.peak_rss_mb or 0.0) for item in items),
                "threads_max": max((item.peak_threads or 0) for item in items),
                "fds_max": max((item.peak_fds or 0) for item in items),
                "errors_total": errors_total,
                "warmup_errors_total": sum(item.warmup_errors for item in items),
                "error_rate_percent": (errors_total / requests_total) * 100 if requests_total else 0.0,
            },
        )
    return rows


def coefficient_of_variation(values: list[float]) -> float:
    if len(values) < MIN_VARIATION_SAMPLES:
        return 0.0
    mean = statistics.mean(values)
    if mean == 0:
        return 0.0
    return (statistics.stdev(values) / mean) * 100


def write_reports(results: list[RunResult], skipped: dict[str, str], args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    aggregate = aggregate_results(results)
    payload = {
        "metadata": {
            "timestamp": timestamp,
            "python": sys.version,
            "platform": platform.platform(),
            "args": vars(args),
            "package_versions": package_versions(["foghttp", "httpx", "zapros", "psutil"]),
            "skipped": skipped,
        },
        "aggregate": aggregate,
        "runs": [asdict(result) for result in results],
    }
    json_path = output_dir / f"{timestamp}.json"
    md_path = output_dir / f"{timestamp}.md"
    latest_json = output_dir / "latest.json"
    latest_md = output_dir / "latest.md"

    json_text = json.dumps(payload, indent=2, sort_keys=True)
    json_path.write_text(json_text + "\n")
    latest_json.write_text(json_text + "\n")

    lines = [
        "# FogHTTP benchmark results",
        "",
        f"- Timestamp: `{timestamp}`",
        f"- Python: `{platform.python_version()}`",
        f"- Platform: `{platform.platform()}`",
        f"- Requests/run: `{args.requests}`",
        f"- Warmup/run: `{args.warmup}`",
        f"- Repeats: `{args.repeats}`",
        f"- Shuffle seed: `{args.seed}`",
        "",
    ]
    if skipped:
        lines.append("## Skipped clients")
        lines.append("")
        for name, reason in skipped.items():
            lines.append(f"- `{name}`: {reason}")
        lines.append("")

    lines.extend(
        [
            "## Aggregate",
            "",
            "| mode | client | scenario | conc | conns | ok/s median | req/s median | cv % | "
            "p50 ms | p95 ms | p99 ms | errors % | max RSS MB | max threads | max fds |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ],
    )
    lines.extend(
        "| {mode} | {client} | {scenario} | {concurrency} | {max_connections} | "
        "{ok_req_s_median:.1f} | {req_s_median:.1f} | {req_s_cv_percent:.1f} | "
        "{p50_ms_median:.2f} | {p95_ms_median:.2f} | {p99_ms_median:.2f} | "
        "{error_rate_percent:.2f} | {rss_mb_max:.1f} | {threads_max} | {fds_max} |".format(**row)
        for row in aggregate
    )

    markdown = "\n".join(lines) + "\n"
    md_path.write_text(markdown)
    latest_md.write_text(markdown)


def package_versions(names: list[str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in names:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "not installed"
    return versions


def scenarios() -> dict[str, Scenario]:
    return {
        "json-small": Scenario(
            name="json-small",
            method="GET",
            path="/json-small",
            expected_content_length=len(SMALL_JSON),
            description="GET small buffered JSON, status and body length check.",
        ),
        "json-decode-small": Scenario(
            name="json-decode-small",
            method="GET",
            path="/json-small",
            expected_json_keys=("ok", "message", "items"),
            description="GET small JSON and call the client's JSON decoder.",
        ),
        "bytes-64k": Scenario(
            name="bytes-64k",
            method="GET",
            path="/bytes-64k",
            expected_content_length=len(BYTES_64K),
            description="GET 64 KiB buffered body.",
        ),
        "post-json-echo": Scenario(
            name="post-json-echo",
            method="POST",
            path="/echo",
            json_body=POST_JSON,
            expected_json_keys=("name", "file_name", "email", "tags"),
            description="POST JSON using each client's JSON request API and decode echoed JSON.",
        ),
        "post-echo-64k": Scenario(
            name="post-echo-64k",
            method="POST",
            path="/echo",
            body=ECHO_64K,
            expected_content_length=len(ECHO_64K),
            description="POST 64 KiB bytes and read the echoed body.",
        ),
        "redirect-get-302": Scenario(
            name="redirect-get-302",
            method="GET",
            path="/redirect/302/json-small",
            expected_json_keys=("ok", "message", "items"),
            expected_redirects=1,
            expected_final_path="/json-small",
            follow_redirects=True,
            description="GET through a 302 redirect and decode final JSON.",
        ),
        "redirect-head-302": Scenario(
            name="redirect-head-302",
            method="HEAD",
            path="/redirect/302/json-small",
            expected_content_length=0,
            expected_redirects=1,
            expected_final_path="/json-small",
            follow_redirects=True,
            description="HEAD through a 302 redirect with no response body.",
        ),
        "redirect-post-303": Scenario(
            name="redirect-post-303",
            method="POST",
            path="/redirect/303/json-small",
            body=REDIRECT_BODY,
            expected_json_keys=("ok", "message", "items"),
            expected_redirects=1,
            expected_final_path="/json-small",
            follow_redirects=True,
            description="POST through a 303 redirect, rewritten to GET.",
        ),
        "redirect-post-307": Scenario(
            name="redirect-post-307",
            method="POST",
            path="/redirect/307/echo",
            body=REDIRECT_BODY,
            expected_content_length=len(REDIRECT_BODY),
            expected_redirects=1,
            expected_final_path="/echo",
            follow_redirects=True,
            description="POST through a 307 redirect, preserving method and body.",
        ),
        "delay-20ms": Scenario(
            name="delay-20ms",
            method="GET",
            path="/delay/20",
            expected_json_keys=("ok", "message", "items"),
            description="GET with 20 ms server delay to compare scheduling overhead.",
        ),
        "pool-contention-20ms": Scenario(
            name="pool-contention-20ms",
            method="GET",
            path="/delay/20",
            expected_json_keys=("ok", "message", "items"),
            max_connections=POOL_CONTENTION_CONNECTIONS,
            description="GET with 20 ms delay and a fixed 10-connection pool.",
        ),
    }


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_int_csv(value: str) -> list[int]:
    return [int(item) for item in parse_csv(value)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare FogHTTP with other Python HTTP clients.")
    parser.add_argument("--clients", default=DEFAULT_CLIENTS)
    parser.add_argument("--modes", default=DEFAULT_MODES)
    parser.add_argument("--concurrency", default="1,10,50,100")
    parser.add_argument("--requests", type=int, default=2000)
    parser.add_argument("--warmup", type=int, default=200)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--max-redirects", type=int, default=DEFAULT_MAX_REDIRECTS)
    parser.add_argument("--seed", type=int, default=BENCHMARK_SEED)
    parser.add_argument("--no-shuffle", action="store_true")
    parser.add_argument("--output-dir", default=str(RESULTS_DIR))
    parser.add_argument("--scenarios", default=DEFAULT_SCENARIOS)
    return parser.parse_args()


def build_plan(
    *,
    clients: list[ClientSpec],
    requested_scenarios: list[str],
    scenario_map: dict[str, Scenario],
    concurrency_levels: list[int],
    repeats: int,
    shuffle: bool,
    seed: int,
) -> list[tuple[Scenario, int, ClientSpec, int]]:
    plan: list[tuple[Scenario, int, ClientSpec, int]] = []
    for scenario_name in requested_scenarios:
        scenario = scenario_map.get(scenario_name)
        if scenario is None:
            continue
        for concurrency in concurrency_levels:
            for spec in clients:
                plan.extend((scenario, concurrency, spec, repeat) for repeat in range(1, repeats + 1))
    if shuffle:
        rng = random.Random(seed)  # noqa: S311
        rng.shuffle(plan)
    return plan


async def main() -> None:
    args = parse_args()
    requested_clients = parse_csv(args.clients)
    requested_modes = parse_csv(args.modes)
    clients, skipped = available_clients(requested_clients, requested_modes)
    if not clients:
        msg = f"No requested clients are available: {skipped}"
        raise SystemExit(msg)

    scenario_map = scenarios()
    requested_scenarios = parse_csv(args.scenarios)
    concurrency_levels = parse_int_csv(args.concurrency)
    plan = build_plan(
        clients=clients,
        requested_scenarios=requested_scenarios,
        scenario_map=scenario_map,
        concurrency_levels=concurrency_levels,
        repeats=args.repeats,
        shuffle=not args.no_shuffle,
        seed=args.seed,
    )
    results: list[RunResult] = []

    async with benchmark_server() as base_url:
        for scenario, concurrency, spec, repeat in plan:
            result = await run_once(
                spec=spec,
                base_url=base_url,
                scenario=scenario,
                concurrency=concurrency,
                requests=args.requests,
                repeat=repeat,
                warmup=args.warmup,
                max_redirects=args.max_redirects,
            )
            results.append(result)

    write_reports(results, skipped, args)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt as exc:
        raise SystemExit(130) from exc
