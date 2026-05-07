# FogHTTP Benchmarks

This directory contains a local benchmark harness for comparing FogHTTP with
other Python HTTP clients.

The benchmark starts an in-process asyncio HTTP/1.1 server and runs each client
against the same endpoints, concurrency levels, request counts, and connection
limits. Results are written as JSON and Markdown under `bench/results/`.

## Run

Build the local extension first:

```bash
uv run maturin develop
```

Run the default benchmark:

```bash
uv run --extra bench python bench/bench_clients.py
```

Run a shorter smoke benchmark:

```bash
uv run --extra bench python bench/bench_clients.py \
  --requests 500 \
  --warmup 100 \
  --repeats 1 \
  --concurrency 1,10,50
```

`psutil`, `httpx`, and `zapros` are optional at import time. Missing clients are
reported as skipped.

## Notes

- Clients are created once per measured run.
- Warmup requests are excluded from measured latency and throughput.
- The server is local, so these numbers measure client overhead and pooling
  behavior more than real network behavior.
- FogHTTP currently targets buffered HTTP/1.1 responses, so this benchmark does
  not compare redirects, cookies, proxies, streaming, or HTTP/2.
