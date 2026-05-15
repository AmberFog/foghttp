# Benchmarks

Benchmark harness and future benchmark reports live in a separate repository:
[github.com/AmberFog/FogHttpBenchmark](https://github.com/AmberFog/FogHttpBenchmark).

Benchmarks run against the local asyncio HTTP/1.1 loopback server from
`bench/`. Results compare client overhead, buffering, redirects, request
backpressure, and scheduling behavior.

## Environment

| Field | Value |
|---|---|
| Date | `2026-05-10` |
| Python | `3.14.0` |
| Platform | `macOS-26.3.1-arm64-arm-64bit-Mach-O` |
| Server | local asyncio HTTP/1.1 loopback |
| Shuffle seed | `20260507` |

## Versions

| Client | Version |
|---|---:|
| FogHTTP | `0.1.3` |
| aiohttp | `3.13.5` |
| httpx | `0.28.1` |
| zapros | `0.11.1` |

## Async Buffered Workloads

Requests/run: `500`, warmup/run: `50`, repeats: `3`, concurrency: `1,10,50,100`.

Scenarios: `json-small`, `json-decode-small`, `bytes-64k`, `post-json-echo`,
`post-echo-64k`, `redirect-get-302`, `redirect-head-302`,
`redirect-post-303`, `redirect-post-307`.

| Client | Wins | Median ok/s | Median p95 ms | Max threads | Max fds | Errors |
|---|---:|---:|---:|---:|---:|---:|
| FogHTTP | `27/36` | `11336.9` | `2.96` | `17` | `258` | `0` |
| aiohttp | `9/36` | `8080.9` | `5.67` | `1` | `207` | `0` |
| zapros | `0/36` | `3743.9` | `8.71` | `1` | `257` | `0` |
| httpx | `0/36` | `832.2` | `673.46` | `1` | `107` | `0` |

FogHTTP stayed within `0.977x` of the fastest row in every async buffered
comparison.

## Async Delay And Pool Contention

Requests/run: `100`, warmup/run: `10`, repeats: `2`, concurrency: `10,50,100`.

Scenarios: `delay-20ms`, `pool-contention-20ms`.

| Client | Wins | Median ok/s | Median p95 ms | Max threads | Max fds | Errors |
|---|---:|---:|---:|---:|---:|---:|
| FogHTTP | `4/6` | `432.7` | `33.78` | `17` | `210` | `0` |
| aiohttp | `2/6` | `431.5` | `37.54` | `1` | `207` | `0` |
| zapros | `0/6` | `396.9` | `43.59` | `1` | `207` | `0` |
| httpx | `0/6` | `393.9` | `211.44` | `1` | `173` | `0` |

## Sync Buffered Workloads

Requests/run: `300`, warmup/run: `30`, repeats: `3`, concurrency: `1,10,50`.

Scenarios: `json-small`, `json-decode-small`, `bytes-64k`, `post-json-echo`,
`redirect-get-302`, `redirect-post-307`.

| Client | Wins | Median ok/s | Median p95 ms | Max threads | Max fds | Errors |
|---|---:|---:|---:|---:|---:|---:|
| FogHTTP | `18/18` | `7202.7` | `0.66` | `68` | `110` | `0` |
| zapros | `0/18` | `3662.5` | `3.31` | `52` | `140` | `0` |
| httpx | `0/18` | `2111.2` | `7.01` | `52` | `67` | `0` |

## Notes

- Higher `ok/s` is better.
- Lower `p95 ms`, threads, fds, and errors are better.
- Sync and async results should be compared separately.
- Local loopback results do not measure real internet latency.
