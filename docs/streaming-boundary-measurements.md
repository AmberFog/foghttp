# Streaming Boundary Copy Experiment

Local development measurements for TASK-324, not a published-release benchmark.
Baseline: `5a60ffd35f9d861064877a6cda401daf60e2cf03`. Candidate: that revision
plus the accompanying download-only patch. Upload behavior is unchanged.

## Protocol Chosen Before Candidate Measurements

Primary metric: boundary conversion nanoseconds for single 64/256 KiB payloads.
The baseline pilot used three fresh processes: 64 KiB 1776-1927 ns, 256 KiB
6923-6950 ns. Require a repeatable improvement exceeding that variation, with
10% as the practical minimum for this experiment. Coalesced and 4 KiB paths are
controls, not an opportunity to select whichever metric improves most.

Whole-stream pilot (64 KiB, concurrency 1) varied by about 6% in throughput
and 9% in first-item latency. Investigate disjoint before/after ranges with a
throughput loss over 10%, first-item increase over the larger of 20%/100 us,
or retained/peak client memory increase over 2 MiB at concurrency 1 and 10 MiB
at concurrency 10. These are local investigation thresholds, not API guarantees
or shared-CI timing gates. Report noisy/overlapping results without claiming
an end-to-end speedup. Allow one noise-explained rerun, then stop.

Use release builds, the same host/toolchain, CPython 3.14.0 and locked orjson
3.11.9. The ignored Rust measurement calls the production ready-frame coalescer
and PyO3 byte constructor; its initial frame handoff matches `read_next_chunk`
(`to_vec()` on baseline, owned `Bytes` on candidate). It excludes transport,
future scheduling and fixture allocation, not the initial conversion. This
is a focused conversion microbenchmark, not full request throughput.

The Python control runs use installed wheels in isolated environments and
`-I`, a separate local server process, a reused explicit client, equal warmup,
and fresh client processes per scenario/repetition. Measure 1 MiB responses
with 4/64/256 KiB wire chunks, sync/async, concurrency 1/10; add 64 KiB drip,
first-chunk close, lines and buffered controls. Record raw output, build and
extension identities. RSS includes the client interpreter/runtime, not the
server; it is not an allocation counter or a proof of leak absence.

## Results

Three paired fresh-process repetitions, alternating baseline/candidate order,
completed after the correctness checks, with no concurrent agent-run builds
or test suites. Raw samples:
[conversion](streaming-boundary-conversion.csv) and
[HTTP controls](streaming-boundary-controls.csv). The controls contain 168 runs
(28 cases x 2 builds x 3 repetitions). All reported zero connection-open
failures and zero active requests after the measured batch; intentional early
close is allowed to increment aborted/failed request counters.

### Boundary Conversion

Nanoseconds per output chunk, median (minimum-maximum); negative delta is faster.
Sizes describe the total output, split evenly for the two-frame case.

| KiB | Frames | Baseline ns | Candidate ns | Time delta |
| --- | --- | --- | --- | --- |
| 4 | 1 | 126.0 (124.1-130.3) | 66.2 (66.1-73.4) | -47.5% |
| 4 | 2 | 181.0 (177.3-197.9) | 140.7 (131.1-143.4) | -22.3% |
| 64 | 1 | 1742.4 (1732.8-1852.7) | 667.4 (661.9-698.9) | -61.7% |
| 64 | 2 | 2656.9 (2457.1-2929.8) | 1492.0 (1415.7-1580.3) | -43.8% |
| 256 | 1 | 6818.5 (6598.2-6850.6) | 3284.1 (3236.0-3766.2) | -51.8% |
| 256 | 2 | 6539.8 (6452.1-6850.8) | 7173.6 (6415.8-7753.6) | +9.7% |

Accept the download optimization for its single-frame boundary gain. Do not
claim a universal gain: the 256 KiB two-frame control has a slower median and
overlapping ranges, so that coalesced result is inconclusive.

### Whole-Stream Controls

Deltas of medians: delivered-data throughput, first-item latency in microseconds,
peak client RSS and RSS after client close in MiB. First-item latency for the
buffered control means complete-response latency. Lines omit delimiters from
the delivered-data count; partial-close bytes depend on transport chunking.
Compare only within a case, never throughput across these modes.

| Client / mode / wire bytes / concurrency | Throughput | First item us | Peak MiB | After close MiB |
| --- | --- | --- | --- | --- |
| sync / bytes / 4096 / 1 | -0.5% | -7 | +1.20 | +1.22 |
| sync / bytes / 4096 / 10 | +0.2% | -11 | +3.06 | +3.11 |
| sync / bytes / 65536 / 1 | +5.9% | -2 | +1.06 | +1.08 |
| sync / bytes / 65536 / 10 | +0.7% | -12 | +4.02 | +4.05 |
| sync / bytes / 262144 / 1 | +1.2% | -2 | +0.52 | +0.50 |
| sync / bytes / 262144 / 10 | -1.0% | -13 | +1.86 | +1.91 |
| sync / drip / 65536 / 1 | +1.0% | +64 | +0.48 | +0.48 |
| sync / drip / 65536 / 10 | -1.8% | +67 | +2.89 | +2.94 |
| sync / close / 65536 / 1 | -14.0% | +36 | -0.03 | -0.08 |
| sync / close / 65536 / 10 | -0.4% | -413 | -0.39 | -0.34 |
| sync / lines / 65536 / 1 | -0.9% | -10 | +0.53 | +0.55 |
| sync / lines / 65536 / 10 | +2.2% | +9 | +0.86 | +0.89 |
| sync / buffered / 65536 / 1 | -6.5% | +20 | +1.34 | +1.36 |
| sync / buffered / 65536 / 10 | +2.1% | +16 | -0.98 | -0.94 |
| async / bytes / 4096 / 1 | +0.2% | -1 | -0.06 | -0.05 |
| async / bytes / 4096 / 10 | +0.8% | -29 | -0.09 | -0.09 |
| async / bytes / 65536 / 1 | +10.3% | -6 | -0.14 | -0.12 |
| async / bytes / 65536 / 10 | +2.4% | +2 | -1.44 | -1.44 |
| async / bytes / 262144 / 1 | +5.3% | -5 | -0.50 | -0.48 |
| async / bytes / 262144 / 10 | +2.9% | -12 | -1.44 | -1.47 |
| async / drip / 65536 / 1 | -0.3% | +98 | -0.05 | -0.06 |
| async / drip / 65536 / 10 | +0.5% | -90 | -1.03 | -1.03 |
| async / close / 65536 / 1 | -5.2% | +28 | -0.27 | -0.28 |
| async / close / 65536 / 10 | +1.0% | +330 | +0.19 | +0.17 |
| async / lines / 65536 / 1 | +1.2% | +21 | +0.09 | +0.09 |
| async / lines / 65536 / 10 | -1.1% | -778 | -0.45 | -0.47 |
| async / buffered / 65536 / 1 | +1.4% | -11 | +0.11 | +0.08 |
| async / buffered / 65536 / 10 | +2.2% | -33 | +2.19 | +2.22 |

None of the predetermined disjoint-range investigation thresholds fired.
These are small local controls, not evidence of a general HTTP speedup.
In particular, sync early-close throughput has a -14% median but overlapping
ranges: 20.18-24.35 MiB/s baseline versus 19.57-24.95 candidate. Completed
early-close requests similarly range 2624-3150/s versus 2539-3244/s; classify
this as noisy, not a demonstrated regression or improvement.

The sync full-stream RSS increase is real in these samples, about 0.5-1.2 MiB
at concurrency 1 and 1.9-4.1 MiB at concurrency 10. It stays within the
preselected local memory budget, but fewer copies must not be marketed as
lower RSS. RSS cannot attribute this to retained Hyper backing versus allocator
reuse. Async byte-stream memory is neutral or lower in this run. Higher
concurrency and platform-specific allocator behavior remain release-level
profiling risks. No ambiguous result was repeatedly rerun.

### Build Identity And Reproduction

- Host: macOS 26.6.2 arm64; Rust 1.95.0, default release profile/system allocator.
- Both measured Python environments: CPython 3.14.0, orjson 3.11.9.
- Dependency pins: Cargo.lock and uv.lock unchanged; PyO3 0.29.0, bytes 1.12.0,
  Tokio 1.52.3, stable ABI floor CPython 3.11.
- Baseline wheel SHA-256:
  `8b86ee79b121e8ab7bd9736b795fe08dd0f7fb502c5db31812c39a237981bb12`.
- Candidate wheel SHA-256:
  `c4ada7c7093d0e9418537b39d8b0ba737d6a4110c7ce0300752453e97eeb5be5`.
- Original JSON logs, wheel environments and compiled measurement executables
  are local ignored artifacts under `target/task324/`; the CSV files retain
  the numeric samples without host-specific paths. Each original control log
  records the actually imported extension path inside its installed-wheel
  environment, never the source-tree extension.

Build each checkout with the same interpreter/toolchain:

```bash
uv run --frozen --extra dev --with "maturin>=1.7,<2" maturin build --release --locked --out target/task324/build --interpreter .venv/bin/python
uv venv --python .venv/bin/python target/task324/env
uv pip install --python target/task324/env/bin/python target/task324/build/*.whl orjson==3.11.9
target/task324/env/bin/python -I scripts/measure_streaming_boundary.py --client async --mode bytes --size 65536 --concurrency 1 --rounds 128
cargo test --release --locked measure_streaming_boundary_conversion -- --ignored --nocapture
```

For the baseline microbenchmark, add only the ignored measurement function to
the baseline's existing state tests, keeping its initial `data.to_vec()`
handoff; the candidate uses `data.clone()` to supply an owned frame. The latter
also pays a refcount operation that a real moved frame avoids. The production
coalescer and PyO3 constructor are called in both binaries. Save the compiled
test executable for each build and alternate them without rebuilding inside
the timing loop. Each case processes 256 MiB for warmup, then 256 MiB measured.
No allocator-count or retained-memory claim is inferred from copy counting.

For HTTP controls, use both clients and concurrency 1/10. Bytes uses each of
4/64/256 KiB; the four other modes use 64 KiB. Use 128 rounds at concurrency 1
and 32 at concurrency 10 for bytes/buffered, 8 rounds for lines, and 16 for
drip/close, always two concurrent warmup rounds. Run each case/build in a
fresh process three times, alternating build order. Preserve failures rather
than dropping samples.

### Validation

- Rust: fmt, clippy with warnings denied, 252 tests; the manual measurement
  is separately ignored in normal test runs and explicitly executed above.
- MSRV 1.88: 252 tests and all-target/all-feature check.
- Python 3.14: targeted streaming/boundary/cancellation/lifecycle 155 tests;
  complete coverage run 1774 tests, followed by the passing 98% coverage gate.
- Pre-commit on all task files; project mypy (177 files) plus the measurement
  script checked separately.
- Release abi3 wheel build and strict abi3audit: no violations or mismatches.
  Canonical installed-wheel smoke passed on CPython 3.11, 3.12, 3.13 and 3.14.
- Linux/manylinux and the full pytest runs on Python 3.11-3.13 remain CI
  validation, not locally claimed passes.

## Ownership And Scope

| Path | Baseline | Candidate / disposition |
| --- | --- | --- |
| Sync download | Hyper `Bytes` -> copied `Vec` -> copied Python `bytes` | Owned `Bytes` crosses the existing oneshot; `PyBytes::new` copies once after the detached wait and after the state lock is released. |
| Async single-frame download | Same full-payload copies, followed by scheduled future delivery | Owned `Bytes` stays in Rust until Python attachment; the existing future setter receives an independent Python copy. |
| Async coalesced download | Eager first-frame copy plus extension/reallocation, then Python copy | Lazily allocate `BytesMut` for the first two ready frames, extend within unchanged limits, freeze without copying, then construct Python `bytes`. Coalesced delivery is not advertised as one-copy. |
| Immutable upload | Normalization keeps `bytes`; every raw send attempt copies into Rust storage | Unchanged. PyO3's optional owner-backed conversion is a candidate, not an accepted optimization. |
| Mutable/view upload | Snapshot during normalization, then raw send copy; queue-full retries can repeat the latter | Unchanged. Retaining a Python owner would widen the lifetime/finalization review and require its own measured benefit. Readonly views do not imply immutable backing. |

Upload was evaluated at the ownership/copy-map level and not selected for
implementation. No upload performance or safety improvement is claimed.
Text decoding, line splitting, pooling, drivers, cancellation and pressure
policy are not rewritten. No public signature, dependency feature, MSRV or
Python-version change is needed.

The native ownership forms come from existing dependencies:
[PyO3 0.29.0](https://github.com/PyO3/pyo3/blob/v0.29.0/src/types/bytes.rs)
and [bytes 1.12.0](https://github.com/tokio-rs/bytes/blob/v1.12.0/src/bytes_mut.rs).
The existing separate benchmark harness remains the release-level comparison;
this small dev-only control script isolates installed builds and the selected
wire chunk sizes without modifying that harness or its release process.

## Correctness Evidence

- Rust coalescer tests: data before deferred errors, EOF, pending, byte target,
  frame cap and no-copy ownership of a single sliced frame after owner drop.
- Python sync/async tests: retained chunks remain `bytes` with exact content
  after later reads and response/client close.
- Existing streaming, GIL, cancellation and lifecycle tests: first data before
  tail release, empty EOF, read timeout, close/cancel during pending reads,
  rejected registration, error delivery, resource release and recovery.

The native state-transition and lock order are unchanged. A single frame may
temporarily retain its larger Hyper backing allocation until the boundary
copy; it cannot keep that storage alive through user-retained Python chunks.
RSS controls check for practical regression, not arbitrary-workload memory
bounds or the separate early-close memory investigation.
