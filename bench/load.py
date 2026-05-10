__all__ = (
    "merge_load_results",
    "outcome_matches",
    "run_load",
)

import asyncio
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue
import time

from bench.clients.base import AsyncClientAdapter, SyncClientAdapter
from bench.models import LoadResult, ResponseOutcome, Scenario


async def run_load(
    client: AsyncClientAdapter | SyncClientAdapter,
    scenario: Scenario,
    url: str,
    concurrency: int,
    requests: int,
    *,
    collect: bool,
) -> LoadResult:
    if requests == 0:
        return LoadResult([], 0, {})
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
