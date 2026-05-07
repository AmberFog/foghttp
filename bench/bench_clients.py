from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
import gc
import importlib
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import sys
import time
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "bench" / "results"
SMALL_JSON = b'{"ok":true,"message":"foghttp benchmark","items":[1,2,3,4]}'
BYTES_64K = b"x" * 65536
ECHO_64K = b"y" * 65536


@dataclass(frozen=True)
class ClientSpec:
    name: str
    factory: Callable[[int], Awaitable[ClientAdapter]]


@dataclass
class RunResult:
    client: str
    scenario: str
    concurrency: int
    requests: int
    repeat: int
    duration_s: float
    requests_per_second: float
    p50_ms: float
    p90_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    errors: int
    process_cpu_s: float
    peak_rss_mb: float | None
    peak_threads: int | None
    peak_fds: int | None
    client_stats: dict[str, Any] | None


class ClientAdapter:
    async def request(self, method: str, url: str, **kwargs: Any) -> int:
        raise NotImplementedError

    async def aclose(self) -> None:
        raise NotImplementedError

    def stats(self) -> dict[str, Any] | None:
        return None


class FogHTTPAdapter(ClientAdapter):
    def __init__(self, client: Any) -> None:
        self.client = client

    async def request(self, method: str, url: str, **kwargs: Any) -> int:
        response = await self.client.request(method, url, **kwargs)
        return int(response.status_code)

    async def aclose(self) -> None:
        await self.client.aclose()

    def stats(self) -> dict[str, Any] | None:
        stats = self.client.stats()
        if hasattr(stats, "__dataclass_fields__"):
            return asdict(stats)
        return dict(stats)


class HTTPXAdapter(ClientAdapter):
    def __init__(self, client: Any) -> None:
        self.client = client

    async def request(self, method: str, url: str, **kwargs: Any) -> int:
        response = await self.client.request(method, url, **kwargs)
        return int(response.status_code)

    async def aclose(self) -> None:
        await self.client.aclose()


class ZaprosAdapter(ClientAdapter):
    def __init__(self, client: Any) -> None:
        self.client = client

    async def request(self, method: str, url: str, **kwargs: Any) -> int:
        if "content" in kwargs:
            kwargs["body"] = kwargs.pop("content")
        response = await self.client.request(method, url, **kwargs)
        status = getattr(response, "status_code", getattr(response, "status", None))
        if status is None:
            msg = "zapros response has no status/status_code attribute"
            raise RuntimeError(msg)
        return int(status)

    async def aclose(self) -> None:
        close = getattr(self.client, "aclose", None)
        if close is None:
            close = getattr(self.client, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result


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
            self._process = psutil.Process()
        except Exception:
            self._process = None
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
            _method, path, _version = first_line.split(" ", 2)
            content_length = int(headers.get("content-length", "0"))
            if content_length:
                body = await reader.readexactly(content_length)
            else:
                body = b""

            connection = headers.get("connection", "").lower()
            keep_alive = connection != "close"
            status = b"200 OK"
            content_type = b"application/octet-stream"
            response_body = b""

            if path.startswith("/json-small"):
                response_body = SMALL_JSON
                content_type = b"application/json"
            elif path.startswith("/bytes-64k"):
                response_body = BYTES_64K
            elif path.startswith("/echo"):
                response_body = body
                content_type = headers.get("content-type", "application/octet-stream").encode()
            elif path.startswith("/delay/"):
                delay_ms = int(path.rsplit("/", 1)[1])
                await asyncio.sleep(delay_ms / 1000)
                response_body = SMALL_JSON
                content_type = b"application/json"
            else:
                status = b"404 Not Found"
                response_body = b"not found"
                content_type = b"text/plain"

            writer.write(
                b"HTTP/1.1 "
                + status
                + b"\r\ncontent-length: "
                + str(len(response_body)).encode()
                + b"\r\ncontent-type: "
                + content_type
                + b"\r\nconnection: "
                + (b"keep-alive" if keep_alive else b"close")
                + b"\r\n\r\n"
                + response_body,
            )
            await writer.drain()
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


async def make_foghttp(max_connections: int) -> ClientAdapter:
    foghttp = importlib.import_module("foghttp")
    limits = foghttp.Limits(
        max_connections=max_connections,
        max_connections_per_host=max_connections,
        max_pending_acquires=max_connections * 10,
    )
    timeouts = foghttp.Timeouts(connect=2.0, read=10.0, write=10.0, pool=5.0, total=30.0)
    return FogHTTPAdapter(foghttp.AsyncClient(limits=limits, timeouts=timeouts))


async def make_httpx(max_connections: int) -> ClientAdapter:
    httpx = importlib.import_module("httpx")
    limits = httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_connections)
    timeout = httpx.Timeout(connect=2.0, read=10.0, write=10.0, pool=5.0)
    return HTTPXAdapter(httpx.AsyncClient(limits=limits, timeout=timeout, trust_env=False))


async def make_zapros(max_connections: int) -> ClientAdapter:
    zapros = importlib.import_module("zapros")
    client_cls = zapros.AsyncClient
    try:
        client = client_cls(max_connections=max_connections)
    except TypeError:
        client = client_cls()
    return ZaprosAdapter(client)


def available_clients(requested: list[str]) -> tuple[list[ClientSpec], dict[str, str]]:
    factories = {
        "foghttp": make_foghttp,
        "httpx": make_httpx,
        "zapros": make_zapros,
    }
    clients: list[ClientSpec] = []
    skipped: dict[str, str] = {}
    for name in requested:
        if name not in factories:
            skipped[name] = "unknown client"
            continue
        module_name = "foghttp" if name == "foghttp" else name
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            skipped[name] = f"{type(exc).__name__}: {exc}"
            continue
        clients.append(ClientSpec(name=name, factory=factories[name]))
    return clients, skipped


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, round((pct / 100) * (len(values) - 1))))
    return values[index]


async def run_once(
    spec: ClientSpec,
    base_url: str,
    scenario: str,
    path: str,
    method: str,
    concurrency: int,
    requests: int,
    repeat: int,
    warmup: int,
) -> RunResult:
    client = await spec.factory(concurrency)
    url = base_url + path
    body = b'{"hello":"world"}' if method == "POST" else None
    if scenario == "post-echo-64k":
        body = ECHO_64K

    try:
        await run_load(client, method, url, concurrency, warmup, body, collect=False)
        gc.collect()
        cpu_start = time.process_time()
        started = time.perf_counter()
        async with ResourceSampler() as sampler:
            latencies, errors = await run_load(
                client,
                method,
                url,
                concurrency,
                requests,
                body,
                collect=True,
            )
        duration = time.perf_counter() - started
        cpu = time.process_time() - cpu_start
        latencies.sort()
        client_stats = client.stats()
    finally:
        await client.aclose()

    return RunResult(
        client=spec.name,
        scenario=scenario,
        concurrency=concurrency,
        requests=requests,
        repeat=repeat,
        duration_s=duration,
        requests_per_second=requests / duration if duration > 0 else 0.0,
        p50_ms=percentile(latencies, 50),
        p90_ms=percentile(latencies, 90),
        p95_ms=percentile(latencies, 95),
        p99_ms=percentile(latencies, 99),
        min_ms=latencies[0] if latencies else 0.0,
        max_ms=latencies[-1] if latencies else 0.0,
        errors=errors,
        process_cpu_s=cpu,
        peak_rss_mb=sampler.peak_rss_mb,
        peak_threads=sampler.peak_threads,
        peak_fds=sampler.peak_fds,
        client_stats=client_stats,
    )


async def run_load(
    client: ClientAdapter,
    method: str,
    url: str,
    concurrency: int,
    requests: int,
    body: bytes | None,
    *,
    collect: bool,
) -> tuple[list[float], int]:
    latencies: list[float] = []
    errors = 0
    queue: asyncio.Queue[int] = asyncio.Queue()
    for index in range(requests):
        queue.put_nowait(index)

    async def worker() -> None:
        nonlocal errors
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            started = time.perf_counter_ns()
            try:
                kwargs = {"content": body} if body is not None else {}
                status = await client.request(method, url, **kwargs)
                if status != 200:
                    errors += 1
            except Exception:
                errors += 1
            finally:
                if collect:
                    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
                    latencies.append(elapsed_ms)
                queue.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(min(concurrency, requests))]
    await queue.join()
    await asyncio.gather(*workers)
    return latencies, errors


def aggregate_results(results: list[RunResult]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, int], list[RunResult]] = {}
    for result in results:
        grouped.setdefault((result.client, result.scenario, result.concurrency), []).append(result)

    rows: list[dict[str, Any]] = []
    for (client, scenario, concurrency), items in sorted(grouped.items()):
        rows.append(
            {
                "client": client,
                "scenario": scenario,
                "concurrency": concurrency,
                "requests": items[0].requests,
                "repeats": len(items),
                "req_s_median": statistics.median(item.requests_per_second for item in items),
                "p50_ms_median": statistics.median(item.p50_ms for item in items),
                "p95_ms_median": statistics.median(item.p95_ms for item in items),
                "p99_ms_median": statistics.median(item.p99_ms for item in items),
                "rss_mb_max": max((item.peak_rss_mb or 0.0) for item in items),
                "threads_max": max((item.peak_threads or 0) for item in items),
                "fds_max": max((item.peak_fds or 0) for item in items),
                "errors_total": sum(item.errors for item in items),
            },
        )
    return rows


def write_reports(results: list[RunResult], skipped: dict[str, str], args: argparse.Namespace) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    aggregate = aggregate_results(results)
    payload = {
        "metadata": {
            "timestamp": timestamp,
            "python": sys.version,
            "platform": platform.platform(),
            "args": vars(args),
            "skipped": skipped,
        },
        "aggregate": aggregate,
        "runs": [asdict(result) for result in results],
    }
    json_path = RESULTS_DIR / f"{timestamp}.json"
    md_path = RESULTS_DIR / f"{timestamp}.md"
    latest_json = RESULTS_DIR / "latest.json"
    latest_md = RESULTS_DIR / "latest.md"

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
            "| client | scenario | conc | req/s median | p50 ms | p95 ms | p99 ms | max RSS MB | max threads | max fds | errors |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ],
    )
    for row in aggregate:
        lines.append(
            "| {client} | {scenario} | {concurrency} | {req_s_median:.1f} | "
            "{p50_ms_median:.2f} | {p95_ms_median:.2f} | {p99_ms_median:.2f} | "
            "{rss_mb_max:.1f} | {threads_max} | {fds_max} | {errors_total} |".format(**row),
        )

    markdown = "\n".join(lines) + "\n"
    md_path.write_text(markdown)
    latest_md.write_text(markdown)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare FogHTTP with other Python HTTP clients.")
    parser.add_argument("--clients", default="foghttp,httpx,zapros")
    parser.add_argument("--concurrency", default="1,10,50,100")
    parser.add_argument("--requests", type=int, default=5000)
    parser.add_argument("--warmup", type=int, default=500)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--scenarios",
        default="json-small,bytes-64k,post-echo,delay-20ms",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    requested_clients = [item.strip() for item in args.clients.split(",") if item.strip()]
    clients, skipped = available_clients(requested_clients)
    if not clients:
        msg = f"No requested clients are available: {skipped}"
        raise SystemExit(msg)

    scenarios = {
        "json-small": ("GET", "/json-small"),
        "bytes-64k": ("GET", "/bytes-64k"),
        "post-echo": ("POST", "/echo"),
        "post-echo-64k": ("POST", "/echo"),
        "delay-20ms": ("GET", "/delay/20"),
    }
    requested_scenarios = [item.strip() for item in args.scenarios.split(",") if item.strip()]
    concurrency_levels = [int(item.strip()) for item in args.concurrency.split(",") if item.strip()]
    results: list[RunResult] = []

    async with benchmark_server() as base_url:
        for scenario in requested_scenarios:
            if scenario not in scenarios:
                continue
            method, path = scenarios[scenario]
            for concurrency in concurrency_levels:
                for spec in clients:
                    for repeat in range(1, args.repeats + 1):
                        result = await run_once(
                            spec=spec,
                            base_url=base_url,
                            scenario=scenario,
                            path=path,
                            method=method,
                            concurrency=concurrency,
                            requests=args.requests,
                            repeat=repeat,
                            warmup=args.warmup,
                        )
                        results.append(result)

    write_reports(results, skipped, args)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        os._exit(130)
