__all__ = (
    "build_plan",
    "run_once",
)

import gc
import random
import time

from bench.constants import DEFAULT_MAX_REDIRECTS
from bench.load import run_load
from bench.models import ClientConfig, ClientSpec, RunResult, Scenario
from bench.resources import ResourceSampler


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


async def run_once(
    *,
    spec: ClientSpec,
    base_url: str,
    scenario: Scenario,
    concurrency: int,
    requests: int,
    repeat: int,
    warmup: int,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
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


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, round((pct / 100) * (len(values) - 1))))
    return values[index]
