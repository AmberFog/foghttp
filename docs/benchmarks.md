# Benchmarks

Benchmark harness and full benchmark reports live in a separate repository:
[github.com/AmberFog/FogHttpBenchmark](https://github.com/AmberFog/FogHttpBenchmark).
Use the `README.md` from the exact recorded benchmark checkout as the canonical
workflow for full-suite setup, execution, and report review.

This page is a benchmark status snapshot, not a marketing scoreboard. Invalid
rows, compatibility gaps, resource-limit errors, and weak spots stay visible
because they are the inputs we use to improve FogHTTP.

Benchmark snapshot last updated: `2026-08-28` from the full published-package
run in `results/full-pypi-foghttp-0.4.1-20260828`.

## 0.4.1 Request-Body Keep-Alive Result

FogHTTP `0.4.0` routed every non-empty buffered or streaming request body
through a no-idle transport client. That protected request-local write-timeout
state, but it also closed every otherwise healthy HTTP/1.1 connection after the
response. Repeated POST workloads therefore created one TCP connection per
request and could exhaust ephemeral ports at benchmark volume.

The `0.4.1` hotfix scopes write-timeout state to the request's assigned
connection use instead. Successful buffered and streaming uploads return the
connection to the normal keep-alive pool. Write timeout, cancellation, upload
source failure, and incomplete request-body paths still abort or close the
assigned connection before another request can reuse it. This is a
resource-lifecycle correction with no public API or schema change.

The full PyPI `0.4.1` run closes the regression loop with the same request
workloads used to expose `0.4.0`:

- All `72/72` FogHTTP rows in `requests` and `48/48` FogHTTP rows in
  `one-upstream` completed without measured or warmup errors.
- Across the 72 sync/async repeat records for `post-json-echo`,
  `post-echo-64k`, and `redirect-post-307`, `0.4.0` opened and closed all
  `52,800` connection assignments and reused none. Published `0.4.1` opened
  `2,913`, reused `49,887` (`94.5%`), closed `15`, and recorded no connection
  open failures or aborts. The opens are the expected initial concurrency
  fan-out plus 15 clean reconnects.
- In `one-upstream`, FogHTTP moved from `2,926` measured errors and `3,162`
  connection-open failures on `0.4.0` to zero of both on `0.4.1`.
- Matching request-body rows improved throughput geomeans by `+41.8%` to
  `+53.9%`, while p95 latency geomeans fell by `31.8%` to `45.6%`.

These results confirm the intended lifecycle repair. They do not turn the full
all-client `requests` report into a valid competitive baseline: Zapros still
fails `redirect-post-307`, so those report-level rankings remain diagnostic.

## Release Smoke Gate

Normal pull-request CI does not use wall-clock benchmark thresholds. Shared CI
hosts are too variable for a small timing delta to be a reliable pass/fail
signal, and the full benchmark matrix is intentionally kept out of every PR.

Before a release, start from a clean checkout of the separate benchmark
repository at a recorded full commit SHA. Pin the exact FogHTTP release candidate
by its full commit SHA and run this bounded local-server smoke from that checkout.
For an unpublished candidate, update the benchmark checkout and verify its lock
before running the smoke:

```bash
candidate_sha="<full-candidate-commit-sha>"
uv add "foghttp @ git+https://github.com/AmberFog/foghttp.git" \
  --rev "$candidate_sha"
uv lock --check
```

After pinning, only the benchmark project manifest and lockfile may differ from
the recorded clean checkout. Record SHA-256 digests of both exact files; any
other harness change must be committed and become the new recorded benchmark
repository SHA before the smoke runs.

Then run:

```bash
candidate_sha="<full-candidate-commit-sha>"
uv run --locked foghttp-benchmark \
  --suite request-builder \
  --clients foghttp \
  --modes async,sync \
  --iterations 100 \
  --warmup 10 \
  --repeats 3 \
  --scenarios absolute-url,json-body,send-prepared-get \
  --no-progress \
  --output-dir "results/release-smoke-${candidate_sha}"
```

The smoke passes when the command exits successfully, the release tag, candidate,
and FogHTTP lock entry all resolve to the same full commit SHA, the report's
`metadata.package_versions.foghttp` value matches the candidate version, all
FogHTTP rows are valid with no unexpected measured or warmup errors, and the
report has no obvious regression against a same-host, same-Python, same-harness
baseline produced with the same suite, clients, modes, iterations, warmup,
repeats, scenarios, and progress settings. A timing change is reviewed as
evidence, not rejected by a fixed percentage; a maintainer records the timing-
review decision and rationale. Dependency-graph differences outside the
intended FogHTTP baseline/candidate change must be explained there.
Classify or rerun `warning`, `invalid`, and `needs-rerun` output before release.
For changes to a specific hot path or resource lifecycle, run the corresponding
full benchmark suite as described in the benchmark repository instead of
expanding this smoke into the normal PR matrix.

Record this evidence in the release-readiness issue or pull request before
publishing:

```text
Candidate version and release-tag full commit SHA:
Source examples smoke CI run URL and CPython 3.11-3.14 statuses:
Installed-wheel smoke CI run URL and CPython 3.11-3.14 statuses:
Benchmark smoke status:
Benchmark repository full commit SHA and clean-start status:
Benchmark project manifest and lockfile SHA-256:
Candidate manifest/lock artifact URI or reproducible patch:
Resolved FogHTTP lock full SHA:
Report metadata FogHTTP version:
Benchmark host, Python, and exact command:
Candidate-specific report artifact URI and SHA-256:
Baseline FogHTTP version and full commit SHA:
Baseline benchmark repository full commit SHA and manifest/lockfile SHA-256:
Baseline manifest/lock artifact URI or reproducible patch:
Baseline host, Python, exact command, report artifact URI, and SHA-256:
Timing-review decision, maintainer, and rationale:
Warnings, reruns, or approved waiver with approver and rationale:
```

Release readiness requires both example smoke paths and either a valid benchmark
report or a waiver approved by a maintainer. A waiver must identify why the
benchmark is not applicable and record the approver; a missing or unknown status
is not release-ready. Any candidate code change or release-tag move invalidates
the record and requires evidence for the new full SHA. An unrecorded harness
delta or manifest, lockfile, report, or baseline digest mismatch also invalidates
the record. A baseline produced with a different harness identity or workload
command is not comparable and cannot satisfy the gate. Local-only files that
are not retained with the release evidence do not satisfy the artifact fields.

## Methodology

- Server: local asyncio HTTP/1.1 loopback server, plus local HTTPS/proxy
  fixtures for the proxy suite.
- Primary benchmark host: `macOS-26.6.2-arm64-arm-64bit-Mach-O`.
- Python: `3.14.0`.
- Shuffle seed: `20260507`.
- Full-run isolation: sequential subprocesses per client/scenario.
- Child cooldown: `15.0s`.
- Run settling: `3.0s` cooldown after high-connection children when opened
  connections exceed `256`.
- Higher `ok/s`, `ops/s`, `req/s`, successful `streams/s`, `MiB/s`, or
  `lines/s` is better.
- Lower `p95 ms`, `p99 ms`, threads, fds, and error counts are better.
- Throughput and latency comparisons are only meaningful for rows with `0`
  measured errors and `0` warmup errors.
- Resource/backpressure suites intentionally trigger `PoolTimeout`,
  `ResponseBodyTooLargeError`, and `ResponseBodyBudgetExceededError`; those are
  expected resource-control outcomes, not benchmark harness failures.
- Reports with `needs-rerun` validity are diagnostic evidence. They must not be
  used as strong all-client performance baselines until the reason is
  classified or rerun.

## Latest Full Snapshot

Primary benchmark data source for this page:

- Result directory:
  `results/full-pypi-foghttp-0.4.1-20260828`.
- Package versions: FogHTTP `0.4.1`, aiohttp `3.14.0`, httpx `0.28.1`,
  httpxyz `0.31.2`, zapros `0.16.0`, and pyreqwest `0.12.4`.
- Platform: `macOS-26.6.2-arm64-arm-64bit-Mach-O`.
- Python: `3.14.0`.
- Benchmark repository base revision:
  [`861e7cddf9134003c7079cb521def6892235c8d2`](https://github.com/AmberFog/FogHttpBenchmark/tree/861e7cddf9134003c7079cb521def6892235c8d2).
- Benchmark `pyproject.toml` SHA-256:
  `56b65255200348d8fbef4ec0d11466c7ce3041437c04259295c91fd33d04329c`.
- Benchmark `uv.lock` SHA-256:
  `9beb2beccabd8aa3f648f7ae0292d30a9a8b2cc0b1e12c8aa460ac71640e5dc1`.

The benchmark worktree contained uncommitted client-compatibility, validity,
reporting, manifest, and lockfile changes when this run was produced. The
result is retained analysis evidence for the published package, but it is not
an immutable clean-checkout release-gate artifact. Future release evidence must
still follow the clean-start and digest requirements above.

Historical comparison sources:

| Role | Result directory | Use |
| --- | --- | --- |
| Primary published run | `results/full-pypi-foghttp-0.4.1-20260828` | Full PyPI `0.4.1` behavior and same-run competitive position. |
| Nearest `0.4.0` baseline | `results/full-foghttp-0.4.0-20260825-010030` | Matching FogHTTP rows on the same host/OS lineage; request-body rows expose the fixed regression. |
| Alternate `0.4.0` diagnostic | `results/full-20260825-085248` | Second same-host run used to distinguish repeatable product signals from run-level drift. |
| Settled historical baseline | `results/full-pypi-foghttp-0.3.5-settled-20260702-200414` | Older OS/harness lineage; useful as context, not as an absolute performance baseline. |

Absolute throughput, latency, memory, thread, and fd values are compared only
within the same host/result lineage. Even same-host cross-run timing changes are
checked against the other clients before being attributed to FogHTTP.

## Release-Level Read

Published FogHTTP `0.4.1` has no unexpected measured or warmup errors in any
general-purpose FogHTTP row. The resource/backpressure suite records only its
expected pressure outcomes and reports zero recovery failures. The full run
therefore confirms the request-body lifecycle repair without exposing a new
functional FogHTTP regression.

The cross-run timing columns below compare matching FogHTTP rows against
`results/full-foghttp-0.4.0-20260825-010030`. They are diagnostic: the new run
also shifts other clients by similar amounts in several suites, so timing alone
is not assigned to FogHTTP without same-run or multi-baseline support.

| Suite | Report validity | FogHTTP evidence | Primary median vs `0.4.0` | p95 geomean vs `0.4.0` | Same-run position | Current judgement |
| --- | --- | ---: | ---: | ---: | --- | --- |
| `requests` | `needs-rerun`: Zapros `redirect-post-307` failures and httpx variation | `72/72` clean | `+1.1%` | `-15.3%` | ranking blocked | POST and redirect-POST throughput is restored; report-level competition remains diagnostic. |
| `client-creation` | `warning`: two noisy Zapros rows | `12/12` clean | `-3.1%` | `-0.9%` | wins `2/12` | Functionally clean but still a startup/lifecycle weakness. |
| `compressed-response` | `needs-rerun`: competitor compatibility/errors | `36/36` clean | `-4.3%` | `+22.5%` | ranking blocked | Same-run position remains strong, but cross-run decode latency deserves a focused controlled rerun. |
| `one-upstream` | `warning`: two noisy httpx rows | `48/48` clean | `+7.3%` | `-7.9%` | wins `48/48` | The `0.4.0` body-path failures are gone and FogHTTP leads every group. |
| `request-builder` | `valid` | `20/20` clean | `-4.2%` | `+5.7%` | wins `20/20` | Still a clear strength; the small cross-run shift matches competitor drift. |
| `response-streaming` | `warning`: expected aiohttp long-line incompatibility | `60/60` clean | `-5.4%` | `+12.9%` | wins `31/60` | Full-body byte streaming is strong; line iteration and peak early-close RSS remain weak. |
| `proxy-connect` | `valid` | `42/42` clean | `-0.2%` | `+15.0%` | wins `41/42` | Explicit proxy, `trust_env`, HTTPS CONNECT, and cold CONNECT remain clean and highly competitive. |
| `resource-backpressure` | `warning`: one noisy FogHTTP body-limit row | expected pressure errors only | n/a | n/a | FogHTTP-only | Limits remain bounded, final buffered bytes return to zero, and `recovery_failures = 0`. |

## Validity And Harness Identity

The full run contains eight suite reports with the following report-level
validity:

- `valid`: `request-builder` and `proxy-connect`.
- `warning`: `client-creation`, `one-upstream`, `response-streaming`, and
  `resource-backpressure`.
- `needs-rerun`: `requests` and `compressed-response`.

The `needs-rerun` causes are outside FogHTTP: Zapros fails
`redirect-post-307`, Zapros-PyReqwest has unexpected small-gzip errors, and
httpx has high-variation rows. Other compression incompatibilities and
aiohttp's long-line streaming incompatibility are classified as expected.
FogHTTP itself has no unexpected measured or warmup errors. This makes the run
valid product evidence for FogHTTP, but it still blocks strong all-client
rankings for the affected reports.

The run also started from a dirty benchmark worktree. The manifest and lockfile
digests above preserve its dependency identity, but the uncommitted harness
changes prevent treating it as an immutable release-gate artifact. A future
benchmark baseline should commit the harness first and retain the exact report
artifact with that revision.

## Request-Body Regression Is Closed

The connection counters provide direct evidence that the `0.4.0` failure is
fixed rather than merely hidden by a throughput change:

| Evidence slice | FogHTTP `0.4.0` | FogHTTP `0.4.1` |
| --- | ---: | ---: |
| Body-path connection assignments | `52,800` | `52,800` |
| Connections opened | `52,800` | `2,913` |
| Connections reused | `0` | `49,887` |
| Connections closed | `52,800` | `15` |
| Connection-open failures | `0` | `0` |

The matching body scenarios improve throughput geomeans by `+41.8%` to
`+53.9%`, with p95 latency geomeans improving by `31.8%` to `45.6%`. In
`one-upstream`, `0.4.1` completes all `158,400` logical requests with zero
errors, reuses `155,468` assignments, and closes only four connections. The
`0.4.0` baseline recorded `2,926` measured errors, `3,162` connection-open
failures, and `79,242` closes in the same suite.

This is a targeted request-body improvement. It should not be generalized into
a claim that every request path became faster.

## Cross-Run Performance Context

Several non-body suites are slower than the primary `0.4.0` run, but the same
direction and magnitude appear across the unchanged comparison clients. The
table shows throughput geomean change for matching rows:

| Suite | FogHTTP | httpx | httpxyz | Interpretation |
| --- | ---: | ---: | ---: | --- |
| `client-creation` | `-1.1%` | `-6.4%` | `-4.5%` | Small shared run-level drift. |
| `compressed-response` | `-10.3%` | `-12.7%` | `-12.1%` | Shared slowdown; focused rerun still warranted because FogHTTP p95 is higher. |
| `request-builder` | `-4.7%` | `-6.1%` | `-6.8%` | Consistent with run-level drift. |
| `response-streaming` | `-6.9%` | `-8.4%` | `-8.8%` | Consistent with run-level drift. |
| `proxy-connect` | `-8.6%` | `-10.2%` | `-9.9%` | Consistent with run-level drift. |

This cross-client normalization does not support a broad new FogHTTP
performance regression. Compression is the one area worth repeating under a
committed, identical harness because its primary-baseline p95 geomean increased
`22.5%`; the alternate `0.4.0` run reduces that signal, so it is not yet a
confirmed product regression.

## Proxy And CONNECT

`proxy-connect` is valid and all `42/42` FogHTTP rows are clean. FogHTTP wins
`41/42` same-run groups and has a `0.999` geomean ratio to each group's winner.
The only loss is sync explicit CONNECT at concurrency `1`, where FogHTTP is
`3.9%` behind httpx. Explicit proxy routing, `trust_env`, HTTPS CONNECT, and
cold CONNECT all complete without lifecycle or proxy counter failures.

The lower cross-run throughput is shared by all three comparison clients, so
the current evidence does not identify a FogHTTP proxy regression.

## Resource And Backpressure

FogHTTP intentionally produces pressure errors in bounded-resource scenarios.
All are expected and every scenario recovers:

| Scenario | Measured expected errors | Warmup errors | Recovery failures | Main outcome |
| --- | ---: | ---: | ---: | --- |
| `active-limit-serial` | `0` | `0` | `0` | Serial active-limit behavior remains clean. |
| `per-origin-isolation` | `0` | `0` | `0` | Per-origin isolation remains clean. |
| `pending-queue-full` | `3,600` | `0` | `0` | Queue pressure is rejected as designed. |
| `pool-timeout-recovery` | `3,534` | `0` | `0` | Pool timeouts recover cleanly. |
| `response-body-limit` | `3,600` | `0` | `0` | Oversized responses are bounded. |
| `aggregate-buffered-budget` | `3,583` | `0` | `0` | Aggregate buffering stays within budget. |

The report is `warning` because one response-body-limit row has `53.2%`
variation, not because a resource invariant failed. Final buffered response
bytes return to zero, `recovery_failures = 0`, and observed limits remain
bounded at 100 pending requests, 10 active requests, and 200 timeout or budget
rejections per applicable repeat.

## Streaming

All `60/60` FogHTTP rows are clean. The report warning is the expected aiohttp
`long-line-1m` incompatibility, not a FogHTTP error. FogHTTP wins `31/60`
same-run groups with a `0.772` geomean ratio to the winner.

The result is workload-dependent:

- FogHTTP wins all six `stream-1m` and `unicode-lines` groups and five of six
  `first-chunk-close-1m` groups.
- It wins no `lines-10k` or `long-line-1m` groups, with geomean ratios of
  `0.390` and `0.348` respectively. Python line iteration remains the clearest
  throughput weakness.
- Peak RSS for FogHTTP `first-chunk-close-1m` is `1080.7 MiB`, down from
  `1542.2 MiB` in the primary `0.4.0` run but still high. Other clients also
  show high peak memory in this workload, so this remains an investigation
  lead rather than evidence of a FogHTTP leak.

## Strong Areas

- The `0.4.0` POST/body-response connection-reuse regression is closed with
  direct lifecycle-counter evidence from the published `0.4.1` package.
- `one-upstream` wins `48/48` same-run groups with no request or connection-open
  failures.
- `request-builder` wins `20/20` groups, and valid `proxy-connect` wins `41/42`.
- Compression is functionally clean for FogHTTP, including compatibility cases
  that fail for some competitors; its report-level ranking remains blocked.
- Resource limits reject work predictably and recover with zero failures.

## Weak Spots And Follow-Ups

| Area | Signal | What to do next |
| --- | --- | --- |
| Line streaming | `lines-10k` and `long-line-1m` geomean ratios are `0.390` and `0.348`. | Profile line splitting, decoding, and iterator overhead with a focused same-harness run. |
| Early-close memory | `first-chunk-close-1m` peaks at `1080.7 MiB`; lower than `0.4.0`, but still high. | Profile client and server buffering separately before calling it a leak or setting a memory gate. |
| Compression | FogHTTP throughput moves with the other clients, but primary-baseline p95 is `+22.5%`. | Rerun compression from a committed identical harness and compare against both `0.4.0` baselines. |
| Client creation | Functionally clean but wins only `2/12` groups. | Keep as a secondary optimization target after streaming and compression evidence is resolved. |
| Benchmark reproducibility | The run used a dirty benchmark worktree. | Commit the compatibility/validity harness changes before retaining the next authoritative baseline. |
| Competitor validity | Zapros redirect and Zapros-PyReqwest gzip failures block two all-client reports. | Classify or fix those cases, then rerun before publishing cross-client rankings. |

## Current Engineering Conclusion

The published `0.4.1` benchmark confirms the intended hotfix: POST and other
request-body paths reuse healthy HTTP/1.1 connections again, connection churn
collapses, and the full one-upstream workload completes without the
connection-open failures seen in `0.4.0`.

There is no evidence of a new broad functional or performance regression in
FogHTTP. The large positive movement is specific to request-body workloads;
the negative cross-run movement elsewhere is mostly shared by comparison
clients and is therefore more consistent with run-level drift. The next useful
engineering work is a committed-harness compression rerun, then focused line-
streaming and early-close memory profiling. Client creation is a lower-priority
optimization. The dirty harness and competitor failures mean this run should
remain an engineering status snapshot, not a clean release-gate artifact or an
unqualified marketing comparison.
