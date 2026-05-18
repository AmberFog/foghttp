# Benchmarks

Benchmark harness and full benchmark reports live in a separate repository:
[github.com/AmberFog/FogHttpBenchmark](https://github.com/AmberFog/FogHttpBenchmark).

The tables below are copied summary snapshots from that repository. The latest
published snapshot currently covers FogHTTP `0.2.0`; new release measurements
are added after they are produced in the benchmark repository. These numbers are
useful for release-to-release comparison, but they are still local loopback
benchmarks, not a universal prediction for real network latency.

## Methodology

- Server: local asyncio HTTP/1.1 loopback server.
- Platform: `macOS-26.3.1-arm64-arm-64bit-Mach-O`.
- Python: `3.14.0`.
- Shuffle seed: `20260507`.
- `sync:aiohttp` is skipped because aiohttp is async-only.
- Higher `ok/s` or `ops/s` is better.
- Lower `p95 ms`, threads, fds, and errors are better.

## Snapshots

| Suite | Latest snapshot | Previous baseline |
|---|---:|---:|
| request workloads | `20260516-102512` | `20260513-231641` |
| client creation | `20260516-013723` | `20260513-231702` |
| resource/backpressure | `20260516-102812` | none |

## Versions

| Client | Latest snapshot | Previous baseline |
|---|---:|---:|
| FogHTTP | `0.2.0` | `0.1.3` |
| aiohttp | `3.13.5` | `3.13.5` |
| httpx | `0.28.1` | `0.28.1` |
| zapros | `0.11.1` | `0.11.1` |

## Request Workloads

Requests/run: `2000`, warmup/run: `200`, repeats: `3`,
concurrency: `1,10,50,100`.

Buffered scenarios: `json-small`, `json-decode-small`, `bytes-64k`,
`post-json-echo`, `post-echo-64k`, `redirect-get-302`,
`redirect-head-302`, `redirect-post-303`, `redirect-post-307`.

Delay/resource scenarios: `delay-20ms`, `pool-contention-20ms`.

### Latest Snapshot: FogHTTP 0.2.0

| Group | Client | Wins | Median ok/s | Median p95 ms | Max threads | Max fds | Errors |
|---|---|---:|---:|---:|---:|---:|---:|
| async buffered | FogHTTP | `33/36` | `12748.0` | `2.01` | `18` | `218` | `0` |
| async buffered | aiohttp | `3/36` | `9467.7` | `2.21` | `2` | `207` | `0` |
| async buffered | zapros | `0/36` | `4033.3` | `6.89` | `2` | `307` | `0` |
| async buffered | httpx | `0/36` | `621.3` | `269.07` | `2` | `207` | `0` |
| async delay/pool | FogHTTP | `6/8` | `451.1` | `25.36` | `18` | `210` | `0` |
| async delay/pool | aiohttp | `2/8` | `450.5` | `26.08` | `2` | `207` | `761` |
| async delay/pool | zapros | `0/8` | `413.1` | `28.91` | `2` | `207` | `0` |
| async delay/pool | httpx | `0/8` | `278.7` | `373.99` | `2` | `207` | `0` |
| sync buffered | FogHTTP | `36/36` | `12958.7` | `1.66` | `118` | `212` | `0` |
| sync buffered | zapros | `0/36` | `3680.4` | `8.54` | `102` | `270` | `0` |
| sync buffered | httpx | `0/36` | `1141.5` | `24.43` | `102` | `207` | `0` |
| sync delay/pool | FogHTTP | `7/8` | `457.7` | `22.61` | `118` | `210` | `0` |
| sync delay/pool | zapros | `1/8` | `439.5` | `24.67` | `102` | `207` | `0` |
| sync delay/pool | httpx | `0/8` | `176.3` | `123.17` | `102` | `207` | `0` |

### FogHTTP 0.2.0 vs 0.1.3

| Group | 0.1.3 median ok/s | 0.2.0 median ok/s | ok/s delta | 0.1.3 median p95 ms | 0.2.0 median p95 ms | p95 delta |
|---|---:|---:|---:|---:|---:|---:|
| async buffered | `12774.7` | `12748.0` | `-0.2%` | `1.98` | `2.01` | `+1.7%` |
| async delay/pool | `447.1` | `451.1` | `+0.9%` | `25.32` | `25.36` | `+0.1%` |
| sync buffered | `13005.4` | `12958.7` | `-0.4%` | `1.57` | `1.66` | `+5.8%` |
| sync delay/pool | `457.8` | `457.7` | `-0.0%` | `23.08` | `22.61` | `-2.1%` |

Request throughput stayed effectively stable across the 0.2.0 resource,
lifecycle, timeout, and safety changes. The sync buffered p95 regression is
small in absolute terms, but it is worth watching in later releases.

## Client Creation And First Request

Iterations/run: `100`, client counts: `1,10,50`, repeats: `3`.

Scenarios: `create-close`, `create-first-request`,
`many-clients-open-close`, `reused-request`.

### Latest Snapshot: FogHTTP 0.2.0

| Group | Client | Wins | Median ops/s | Median p95 ms | Peak threads | Peak fds | Errors |
|---|---|---:|---:|---:|---:|---:|---:|
| async creation | FogHTTP | `5/6` | `46610.4` | `0.016` | `1` | `5` | `0` |
| async creation | zapros | `0/6` | `32333.0` | `0.021` | `0` | `2` | `0` |
| async creation | aiohttp | `1/6` | `17033.0` | `0.054` | `0` | `2` | `0` |
| async creation | httpx | `0/6` | `337.1` | `3.098` | `0` | `1` | `0` |
| sync creation | FogHTTP | `6/6` | `41305.8` | `0.019` | `1` | `5` | `0` |
| sync creation | zapros | `0/6` | `36997.9` | `0.021` | `0` | `2` | `0` |
| sync creation | httpx | `0/6` | `351.8` | `2.938` | `0` | `2` | `0` |

### FogHTTP 0.2.0 vs 0.1.3

| Group | 0.1.3 median ops/s | 0.2.0 median ops/s | ops/s delta | 0.1.3 median p95 ms | 0.2.0 median p95 ms | p95 delta |
|---|---:|---:|---:|---:|---:|---:|
| async creation | `18479.4` | `46610.4` | `+152.2%` | `0.068` | `0.016` | `-76.3%` |
| sync creation | `16517.6` | `41305.8` | `+150.1%` | `0.060` | `0.019` | `-68.6%` |

The main 0.2.0 performance improvement is client lifecycle cost. Lazy Rust
transport initialization removes the old short-lived-client thread/fd spike:
FogHTTP peak thread delta dropped from `50` to `1`, and peak fd delta dropped
from `150` to `5` in the creation suite.

## Resource And Backpressure Workloads

Requests/run: `200`, warmup/run: `0`, repeats: `3`, concurrency: `10,50,100`.

Scenarios: `active-limit-serial`, `pending-queue-full`,
`per-origin-isolation`, `pool-timeout-recovery`, `response-body-limit`.

| Mode | Scenario | Total ok | Median errors % | Median p95 ms | Peak active | Peak pending | Pool timeouts | Recovery failures | Max threads | Max fds |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| async | active-limit-serial | `1800` | `0.00` | `1062.90` | `1` | `99` | `0` | `0` | `3` | `13` |
| async | pending-queue-full | `0` | `100.00` | `2.83` | `0` | `0` | `200` | `0` | `3` | `11` |
| async | per-origin-isolation | `1800` | `0.00` | `537.25` | `2` | `98` | `0` | `0` | `4` | `15` |
| async | pool-timeout-recovery | `34` | `99.00` | `9.37` | `1` | `99` | `199` | `0` | `3` | `13` |
| async | response-body-limit | `0` | `100.00` | `16.59` | `1` | `99` | `0` | `0` | `3` | `13` |
| sync | active-limit-serial | `1800` | `0.00` | `1053.51` | `1` | `99` | `0` | `0` | `103` | `13` |
| sync | pending-queue-full | `0` | `100.00` | `0.02` | `0` | `0` | `200` | `0` | `3` | `11` |
| sync | per-origin-isolation | `1800` | `0.00` | `517.53` | `2` | `99` | `0` | `0` | `104` | `15` |
| sync | pool-timeout-recovery | `32` | `99.00` | `7.19` | `1` | `99` | `199` | `0` | `103` | `13` |
| sync | response-body-limit | `0` | `100.00` | `13.76` | `1` | `99` | `0` | `0` | `103` | `13` |

Resource benchmarks confirm the current request-slot model:

- `active-limit-serial` holds active requests at `1`.
- `per-origin-isolation` holds total active requests at `2` with one active
  request per origin.
- `pending-queue-full` fails fast with `PoolTimeout` and does not leak pending
  or active slots.
- `pool-timeout-recovery` reports expected `PoolTimeout` outcomes and no
  recovery failures.
- `response-body-limit` fails with `ResponseBodyTooLargeError` without active
  request leaks.

## Notes

- Sync and async results should be compared separately.
- Thread counts are not directly comparable between sync and async modes:
  sync workloads also include Python worker threads from the benchmark harness.
- Resource/backpressure scenarios intentionally produce errors in some cases;
  those errors are the expected behavior under configured limits.
