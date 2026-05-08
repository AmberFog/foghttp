# FogHTTP Benchmarks

This directory contains a local benchmark harness for comparing FogHTTP with
other Python HTTP clients.

The benchmark starts an in-process asyncio HTTP/1.1 server and runs each client
against the same endpoints, concurrency levels, request counts, connection
limits, and redirect settings. Results are written as JSON and Markdown under
`bench/results/`.

## Run

Build the local extension first:

```bash
uv run maturin develop
```

Run the default benchmark:

```bash
uv run --extra bench python bench/bench_clients.py
```

Run both async and sync clients:

```bash
uv run --extra bench python bench/bench_clients.py \
  --modes async,sync
```

Run a shorter smoke benchmark:

```bash
uv run --extra bench python bench/bench_clients.py \
  --requests 100 \
  --warmup 20 \
  --repeats 1 \
  --concurrency 1,10 \
  --clients foghttp,httpx \
  --scenarios json-small,json-decode-small,redirect-get-302,redirect-post-307 \
  --output-dir /tmp/foghttp-bench-smoke
```

`httpx`, `zapros`, `psutil`, and `faker` live in the `bench` extra. Missing
clients are still reported as skipped, so the same command can be used when only
some comparison clients are installed.

## Scenarios

The default scenario set covers:

- `json-small`: small buffered JSON response with status and body length check.
- `json-decode-small`: small JSON response plus client-side JSON decode.
- `bytes-64k`: 64 KiB buffered download.
- `post-json-echo`: JSON request API plus JSON decode of the echoed body.
- `post-echo-64k`: 64 KiB bytes upload and echoed download.
- `redirect-get-302`: GET through a 302 redirect to JSON.
- `redirect-head-302`: HEAD through a 302 redirect with no response body.
- `redirect-post-303`: POST through a 303 redirect, rewritten to GET.
- `redirect-post-307`: POST through a 307 redirect, preserving method and body.
- `delay-20ms`: delayed response for scheduling overhead.
- `pool-contention-20ms`: delayed response with a fixed 10-connection pool.

## Notes

- Clients are created once per measured run.
- Warmup requests are excluded from measured latency and throughput.
- Run order is shuffled with a deterministic seed by default. Use `--no-shuffle`
  to restore declaration order.
- The table uses successful requests per second (`ok/s`) as the primary
  throughput metric and also reports attempted request throughput, coefficient
  of variation, warmup errors, and measured errors in JSON.
- Sync and async clients are reported with an explicit `mode` column. Compare
  rows inside the same mode first; sync concurrency is driven by worker threads.
- The server is local, so these numbers measure client overhead and pooling
  behavior more than real network behavior.
- FogHTTP currently targets buffered HTTP/1.1 responses. The benchmark now
  covers redirects, but does not compare cookies, proxies, streaming, or HTTP/2.
