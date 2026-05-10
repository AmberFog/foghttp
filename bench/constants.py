__all__ = (
    "ASYNC_MODE",
    "BENCHMARK_SEED",
    "DEFAULT_CLIENTS",
    "DEFAULT_CONCURRENCY",
    "DEFAULT_MAX_REDIRECTS",
    "DEFAULT_MODES",
    "DEFAULT_REPEATS",
    "DEFAULT_REQUESTS",
    "DEFAULT_SCENARIOS",
    "DEFAULT_WARMUP",
    "MAX_SPLIT_ONCE",
    "MIN_VARIATION_SAMPLES",
    "RESULTS_DIR",
    "ROOT",
    "SYNC_MODE",
)

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "bench" / "results"

ASYNC_MODE = "async"
SYNC_MODE = "sync"

DEFAULT_CLIENTS = "foghttp,httpx,aiohttp,zapros"
DEFAULT_MODES = ASYNC_MODE
DEFAULT_CONCURRENCY = "1,10,50,100"
DEFAULT_REQUESTS = 2000
DEFAULT_WARMUP = 200
DEFAULT_REPEATS = 3
DEFAULT_MAX_REDIRECTS = 20
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

BENCHMARK_SEED = 20260507
MIN_VARIATION_SAMPLES = 2
MAX_SPLIT_ONCE = 1
