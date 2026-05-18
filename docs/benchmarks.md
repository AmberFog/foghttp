# Benchmarks

Benchmark harness and full benchmark reports live in a separate repository:
[github.com/AmberFog/FogHttpBenchmark](https://github.com/AmberFog/FogHttpBenchmark).

The tables below are copied summary snapshots from that repository. They are
useful for release-to-release comparison, but they are still local loopback
benchmarks, not a universal prediction for real network latency.

## Methodology

- Server: local asyncio HTTP/1.1 loopback server.
- Platform: `macOS-26.3.1-arm64-arm-64bit-Mach-O`.
- Python: `3.14.0`.
- Shuffle seed: `20260507`.
- `sync:aiohttp` is skipped because aiohttp is async-only.
- Some suites skip clients that do not expose comparable APIs.
- Higher `ok/s` or `ops/s` is better.
- Lower `p95 ms`, threads, fds, and errors are better.

## Snapshots

| Suite | Latest snapshot | Previous FogHTTP baseline |
|---|---:|---:|
| request workloads | `20260518-131322` | `20260517-220500` |
| client creation | `20260518-120955` | `20260517-220550` |
| resource/backpressure | `20260518-120926` | `20260517-220805` |
| request builder | `20260518-120300` | none |
| one upstream | `20260518-120707` | none |

## Versions

| Client | Latest snapshot | Previous FogHTTP baseline |
|---|---:|---:|
| FogHTTP | `0.3.0` | `0.2.1` |
| aiohttp | `3.13.5` | `3.13.5` |
| httpx | `0.28.1` | `0.28.1` |
| zapros | `0.11.1` | `0.11.1` |

## Release Comparison

The `0.3.0` release added the unified request builder pipeline, client defaults,
form-urlencoded `data=`, body-source validation, stricter security validation,
and redaction. The hot request path stayed stable, but short-lived client
creation regressed and needs follow-up work.

| Suite | Rows | Throughput/primary delta | p95 delta | Notes |
|---|---:|---:|---:|---|
| requests | `88` | `-0.0%` geomean | `-2.4%` | Request throughput stayed effectively flat; p95 improved slightly overall. |
| client creation | `12` | `-29.1%` geomean | `+75.7%` | Clear regression in short-lived client scenarios, especially many-clients-open-close. |
| resource/backpressure | `30` | `-1.7%` geomean | `-13.4%` | Resource semantics held; async pressure p95 needs attention, sync p95 improved. |

Competitive request wins for FogHTTP moved from `83/88` to `75/88`. That is
still a strong position, but it is a signal to keep watching mid-concurrency
request variability rather than only aggregate medians.

## Request Workloads

Requests/run: `2000`, warmup/run: `200`, repeats: `3`,
concurrency: `1,10,50,100`.

Buffered scenarios: `json-small`, `json-decode-small`, `bytes-64k`,
`post-json-echo`, `post-echo-64k`, `redirect-get-302`,
`redirect-head-302`, `redirect-post-303`, `redirect-post-307`.

Delay/resource scenarios: `delay-20ms`, `pool-contention-20ms`.

### Latest Snapshot: FogHTTP 0.3.0

| Group | Client | Wins | Median ok/s | Median p95 ms | Max threads | Max fds | Errors |
|---|---|---:|---:|---:|---:|---:|---:|
| async buffered | FogHTTP | `29/36` | `12919.2` | `2.04` | `18` | `213` | `0` |
| async buffered | aiohttp | `7/36` | `9752.6` | `2.24` | `2` | `207` | `0` |
| async buffered | zapros | `0/36` | `4104.5` | `6.24` | `2` | `307` | `0` |
| async buffered | httpx | `0/36` | `652.1` | `266.99` | `2` | `207` | `0` |
| async delay/pool | FogHTTP | `5/8` | `437.1` | `25.41` | `18` | `210` | `0` |
| async delay/pool | aiohttp | `2/8` | `419.7` | `26.99` | `2` | `207` | `780` |
| async delay/pool | httpx | `1/8` | `290.2` | `39.19` | `2` | `207` | `0` |
| async delay/pool | zapros | `0/8` | `394.6` | `30.35` | `2` | `207` | `0` |
| sync buffered | FogHTTP | `36/36` | `12925.4` | `1.79` | `118` | `212` | `0` |
| sync buffered | zapros | `0/36` | `3880.4` | `8.08` | `102` | `273` | `0` |
| sync buffered | httpx | `0/36` | `1104.8` | `33.25` | `102` | `207` | `0` |
| sync delay/pool | FogHTTP | `5/8` | `441.8` | `23.89` | `118` | `210` | `0` |
| sync delay/pool | httpx | `2/8` | `179.7` | `115.91` | `102` | `207` | `0` |
| sync delay/pool | zapros | `1/8` | `426.8` | `24.41` | `102` | `207` | `0` |

### FogHTTP 0.3.0 vs 0.2.1

| Segment | Rows | Throughput delta | p95 delta |
|---|---:|---:|---:|
| overall | `88` | `-0.0%` | `-2.4%` |
| async | `44` | `-0.2%` | `-2.5%` |
| sync | `44` | `+0.1%` | `-2.3%` |

Top request improvements were mostly POST/redirect high-concurrency rows. Top
regressions were mid-concurrency async JSON/POST rows and sync 64 KiB body rows.
Because the overall geomean is flat, this looks more like request-path
variability and extra per-request bookkeeping cost than a broad transport
slowdown.

## Client Creation And First Request

Iterations/run: `100`, client counts: `1,10,50`, repeats: `3`.

Scenarios: `create-close`, `create-first-request`,
`many-clients-open-close`, `reused-request`.

### Latest Snapshot: FogHTTP 0.3.0

| Mode | Client | Wins | Median ops/s | Median p95 ms | Peak threads | Peak fds | Errors |
|---|---|---:|---:|---:|---:|---:|---:|
| async | FogHTTP | `2/6` | `34181.7` | `0.038` | `1` | `5` | `0` |
| async | zapros | `3/6` | `30111.0` | `0.032` | `0` | `2` | `0` |
| async | aiohttp | `1/6` | `16541.5` | `0.046` | `0` | `2` | `0` |
| async | httpx | `0/6` | `345.2` | `2.966` | `0` | `1` | `0` |
| sync | zapros | `4/6` | `35104.3` | `0.021` | `0` | `2` | `0` |
| sync | FogHTTP | `2/6` | `30963.6` | `0.034` | `1` | `5` | `0` |
| sync | httpx | `0/6` | `355.8` | `2.830` | `0` | `2` | `0` |

### FogHTTP 0.3.0 vs 0.2.1

| Segment | Rows | ops/s delta | p95 delta |
|---|---:|---:|---:|
| overall | `12` | `-29.1%` | `+75.7%` |
| async | `6` | `-34.0%` | `+89.7%` |
| sync | `6` | `-24.0%` | `+62.7%` |
| many-clients-open-close | `6` | `-40.5%` | `+139.7%` |

This is the main regression in the latest benchmark set. FogHTTP is still much
faster than HTTPX for short-lived clients, but it lost the clear lead over
zapros in many short-lived-client rows. The likely cause is added Python-side
construction work from the `0.3.0` request-builder/defaults foundation:
validated config snapshots, builder objects, headers/params defaults, and
additional safety surfaces. This needs profiling rather than guessing from
aggregate numbers.

## Request Builder

Iterations/run: `5000`, warmup/run: `500`, repeats: `3`.

This suite measures request construction without network I/O, plus a prepared
request send case through the local loopback server. aiohttp and zapros are
skipped because the suite requires comparable `build_request` support.

| Mode | Client | Kind | Rows | Median ops/s | Median p95 ms | Max threads | Max fds | Errors |
|---|---|---|---:|---:|---:|---:|---:|---:|
| async | FogHTTP | build | `9` | `159328.5` | `0.0066` | `3` | `8` | `0` |
| async | httpx | build | `9` | `44688.7` | `0.0280` | `3` | `8` | `0` |
| async | FogHTTP | send-prepared | `1` | `8150.8` | `0.1781` | `3` | `12` | `0` |
| async | httpx | send-prepared | `1` | `1892.5` | `0.7594` | `3` | `9` | `0` |
| sync | FogHTTP | build | `9` | `159779.5` | `0.0069` | `3` | `7` | `0` |
| sync | httpx | build | `9` | `45216.0` | `0.0304` | `3` | `7` | `0` |
| sync | FogHTTP | send-prepared | `1` | `10346.6` | `0.1315` | `3` | `12` | `0` |
| sync | httpx | send-prepared | `1` | `3683.6` | `0.4084` | `3` | `9` | `0` |

FogHTTP request building is about `3.5x` HTTPX median throughput in both sync
and async modes. Prepared send is about `4.3x` HTTPX in async and `2.8x` in
sync. This is a strong result for the new request-builder foundation: the
feature added real ergonomics without making request construction slow.

## One Upstream Client Defaults

Requests/run: `1000`, warmup/run: `100`, repeats: `3`,
concurrency: `1,10,50`.

This suite compares direct requests with `base_url`, client defaults, prepared
requests, JSON bodies, and form bodies against one upstream.

| Mode | Client | Rows | Median ok/s | Median p95 ms | Max threads | Max fds | Errors |
|---|---|---:|---:|---:|---:|---:|---:|
| async | FogHTTP | `24` | `9689.0` | `1.30` | `18` | `110` | `0` |
| async | httpx | `24` | `1521.9` | `6.57` | `2` | `107` | `0` |
| sync | FogHTTP | `24` | `10355.0` | `1.07` | `68` | `110` | `0` |
| sync | httpx | `24` | `1834.7` | `6.44` | `52` | `107` | `0` |

The important signal is not only that FogHTTP is faster in this local suite.
`base_url`, default headers, default params, prepared requests, JSON, and form
requests stay close to the direct-request baseline. That means the new
ergonomics are cheap on the hot path.

## Resource And Backpressure Workloads

Requests/run: `200`, warmup/run: `0`, repeats: `3`,
concurrency: `10,50,100`.

Scenarios: `active-limit-serial`, `pending-queue-full`,
`per-origin-isolation`, `pool-timeout-recovery`, `response-body-limit`.

| Mode | Scenario | Total ok | Median errors % | Median p95 ms | Peak active | Peak pending | Pool timeouts | Recovery failures | Max threads | Max fds |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| async | active-limit-serial | `1800` | `0.00` | `1067.16` | `1` | `99` | `0` | `0` | `3` | `13` |
| async | pending-queue-full | `0` | `100.00` | `3.82` | `0` | `0` | `200` | `0` | `3` | `11` |
| async | per-origin-isolation | `1800` | `0.00` | `533.52` | `2` | `98` | `0` | `0` | `4` | `15` |
| async | pool-timeout-recovery | `32` | `99.00` | `9.33` | `1` | `99` | `199` | `0` | `3` | `13` |
| async | response-body-limit | `0` | `100.00` | `15.36` | `1` | `99` | `0` | `0` | `3` | `14` |
| sync | active-limit-serial | `1800` | `0.00` | `1053.65` | `1` | `99` | `0` | `0` | `103` | `15` |
| sync | pending-queue-full | `0` | `100.00` | `0.02` | `0` | `0` | `200` | `0` | `3` | `11` |
| sync | per-origin-isolation | `1800` | `0.00` | `525.37` | `2` | `98` | `0` | `0` | `104` | `15` |
| sync | pool-timeout-recovery | `33` | `99.00` | `7.23` | `1` | `99` | `199` | `0` | `103` | `13` |
| sync | response-body-limit | `0` | `100.00` | `14.68` | `1` | `99` | `0` | `0` | `103` | `13` |

Resource benchmarks confirm the request-slot model:

- `active-limit-serial` holds active requests at `1`.
- `per-origin-isolation` holds total active requests at `2` with one active
  request per origin.
- `pending-queue-full` fails fast with `PoolTimeout` and does not leak pending
  or active slots.
- `pool-timeout-recovery` reports expected `PoolTimeout` outcomes and no
  recovery failures.
- `response-body-limit` fails with `ResponseBodyTooLargeError` without active
  request leaks.

## Current Analysis

What looks strong:

- Request throughput stayed effectively stable from `0.2.1` to `0.3.0` even
  after adding request builder, defaults, body validation, redaction, and
  stronger safety checks.
- Sync buffered workloads are still the strongest competitive area:
  FogHTTP won `36/36` sync buffered groups.
- The request-builder suite is a strong Rust/Python design signal: Python API
  ergonomics did not make construction slow, and prepared sends remain cheap.
- One-upstream workloads show that `base_url`, default headers, default params,
  prepared requests, JSON, and form requests are effectively low-overhead.
- Resource/backpressure behavior is still predictable: no active/pending leaks
  and no recovery failures in the latest resource suite.

What needs attention:

- Short-lived client creation regressed in `0.3.0`. The worst area is
  `many-clients-open-close`, where primary throughput fell by `40.5%` geomean
  and p95 increased by `139.7%`. This should be profiled before more constructor
  work is added.
- Async resource pressure p95 worsened in some expected-error cases, especially
  `pending-queue-full`. The behavior is correct, but the fast-fail path should
  stay cheap under pressure.
- The request suite max RSS moved from `267.4 MB` to `356.1 MB`. This is a
  process-level maximum from a shuffled local benchmark, not proof of a leak,
  but it is a good reason to add dedicated memory/soak measurements and an
  aggregate buffered memory budget.
- FogHTTP still uses more threads than pure-Python async clients because each
  active Rust transport owns Tokio runtime resources. That is an intentional
  trade-off today, but the shared/lazy runtime story should stay on the roadmap.

Follow-up work:

- Profile and reduce short-lived client construction overhead without weakening
  the request-builder contract.
- Add aggregate buffered memory budget for concurrent responses.
- Add acquire latency and queue pressure metrics.
- Add per-origin pressure diagnostics.
- Add fault-injection tests around cancellation storms, partial reads, abrupt
  close, and pool recovery.
- Keep the benchmark page honest: regressions are not hidden; they become the
  next engineering targets.

## Notes

- Sync and async results should be compared separately.
- Thread counts are not directly comparable between sync and async modes:
  sync workloads also include Python worker threads from the benchmark harness.
- Resource/backpressure scenarios intentionally produce errors in some cases;
  those errors are the expected behavior under configured limits.
- Local loopback benchmarks are useful for regression tracking, but production
  network behavior still needs workload-specific validation.
