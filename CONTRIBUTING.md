# Contributing to FogHTTP

Thank you for taking the time to improve FogHTTP.

FogHTTP is an early-stage HTTP client for Python with a Rust transport core. The
project is intentionally focused: it is built for controlled service-to-service
HTTP workloads where explicit lifecycle, predictable resource usage,
cancellation, redirect safety, TLS trust boundaries, and request pressure
visibility matter more than broad browser-like feature parity.

The project values engineers who are interested in serious implementation work:
debugging, measurement, API design, resource ownership, security boundaries, and
tests. Project discussions should stay focused on engineering work rather than
political, religious, ideological, or other unrelated debates.

AI tools are allowed, but they do not replace engineering ownership. Every line
submitted to FogHTTP must be understood, reviewed, tested, and maintainable by a
human contributor.

Until version `0.5.0`, backward compatibility is not guaranteed. The project
still tries to keep public interfaces stable and avoid unnecessary breaking
changes.

## Project Channels

Use the public GitHub project spaces for normal project communication:

- maintainer: [GefMar](https://github.com/GefMar)
- general questions, roadmap, support, and community concerns:
  [GitHub Discussions](https://github.com/AmberFog/foghttp/discussions)
- bugs and focused feature requests:
  [GitHub Issues](https://github.com/AmberFog/foghttp/issues)
- pull requests and code review:
  [GitHub Pull Requests](https://github.com/AmberFog/foghttp/pulls)

Do not post secrets, credentials, private customer data, or unpublished
security vulnerability details in public discussions or issues. For security
reports, follow [SECURITY.md](./SECURITY.md).

## Good Contributions

Good contributions usually make FogHTTP safer, clearer, more observable, or
easier to adopt without weakening its resource-control model.

Useful contribution areas include:

- bug fixes with focused regression tests
- documentation that matches the current behavior
- tests for lifecycle, cancellation, timeouts, redirects, TLS, and backpressure
- small compatibility improvements for the existing request/response API
- performance work backed by benchmarks or a clear measurement plan
- public API refinements discussed before implementation

Large feature-parity additions are not automatically a good fit. Streaming,
cookies, auth helpers, proxy support, retry policy, HTTP/2, and telemetry
exporters need careful design because they touch resource ownership, security,
and Python/Rust boundaries.

## AI-Assisted Contributions

FogHTTP is not opposed to AI-assisted development. Contributors may use AI tools
for exploration, refactoring support, test ideas, documentation drafts, or code
generation.

The standard is simple: the human contributor is responsible for the result.

If you cannot write code without AI, FogHTTP is not the right project for you.
This is a hard requirement, not a preference. AI-assisted work is welcome only
from contributors who can still design, implement, debug, review, and maintain
the code themselves without AI assistance.

Do not submit AI-generated or vibe-coded changes that you cannot explain,
debug, test, and maintain yourself. A pull request is not acceptable just
because an AI tool produced plausible code or because the tests happened to
pass locally.

AI-assisted changes must meet the same bar as any other contribution:

- the design must fit FogHTTP's architecture and resource model
- the code must be reviewed by the human author before submission
- behavior must be covered by focused tests
- performance-sensitive changes must be checked for latency, memory, runtime,
  allocation, contention, or client lifecycle regressions
- public API and documentation changes must be intentional
- security-sensitive paths must be checked for leaks, unsafe defaults, resource
  exhaustion, cancellation bugs, and redirect or TLS regressions
- the contributor must be able to answer review questions about the code

People who depend on AI to write code they do not fully understand do not belong
in this project. AI can assist engineering judgment; it cannot replace it.

## Performance Regressions

FogHTTP is performance-sensitive software. Passing tests are necessary, but they
are not enough. A change can be functionally correct and still make users pay
through worse latency, higher memory usage, extra allocations, more threads,
slower client creation, lock contention, weaker cancellation behavior, or
degraded high-concurrency throughput.

Contributors must think about performance as part of correctness, especially
when touching:

- Rust transport code
- Python/Rust boundary code
- request building and response construction
- redirects and replay policy
- decompression and buffered body handling
- TLS setup
- runtime creation and shutdown
- resource limits, acquire gates, pressure metrics, and diagnostics
- cancellation, close, timeout, and failure paths

If a change affects a hot path or resource lifecycle, include an explanation of
the expected performance impact. Use targeted benchmarks, profiling, or before
and after measurements when the risk is not obvious.

Do not treat "all tests pass" as proof that a change is safe. Tests can miss
performance regressions. Review must still ask what the change costs under load
and whether that cost fits FogHTTP's goal: predictable, observable,
high-concurrency outbound HTTP.

## Before You Start

Before opening a pull request:

1. Check the existing documentation and limitations.
2. Search open issues for related work.
3. Open or comment on an issue before starting a large change, public API
   change, Rust transport change, or behavior change that could affect
   production users.
4. Keep the scope small enough to review safely.

Security issues should not be reported through public issues. See
[SECURITY.md](./SECURITY.md).

## Development Setup

FogHTTP requires:

- Python `>=3.11`
- a Rust toolchain with `cargo`
- `uv`

Install the local extension for development:

```bash
uv run --extra dev --with "maturin>=1.7,<2" maturin develop
```

Run the Python test suite with coverage:

```bash
uv run --extra dev coverage run -m pytest
uv run --extra dev coverage report -m
```

Run the project checks:

```bash
uv run --extra dev pre-commit run --all-files --show-diff-on-failure
```

When changing Rust code, also run the relevant Rust checks:

```bash
cargo fmt --check
cargo test --all-targets
```

Use narrower test commands while iterating, then run the broader checks before
submitting.

## Engineering Expectations

FogHTTP favors explicit behavior over hidden convenience.

Please keep these constraints in mind:

- clients own transport resources explicitly through `close()` / `aclose()`
- sync and async clients should share the same request model where practical
- resource limits, pending queues, and pressure diagnostics must describe the
  real transport behavior
- cancellation, close, timeout, and failure paths need tests, not only happy
  paths
- debug/error surfaces must not leak credentials, sensitive headers, URL
  secrets, or request/response bodies
- TLS verification must stay enabled; FogHTTP intentionally does not expose
  `verify=False`
- redirects must remain conservative about cross-origin credential forwarding,
  body replay, and HTTPS-to-HTTP downgrades
- public docs and examples must match implemented behavior

If a change touches the Python/Rust boundary, pay special attention to resource
ownership, task cancellation, runtime shutdown, GIL interaction, and error
mapping.

## Code Style

Follow the existing project style. In general:

- keep modules organized by responsibility
- prefer typed, inspectable Python APIs
- keep Rust ownership and lifecycle boundaries explicit
- use clear names instead of short local aliases
- add abstractions only when they remove real complexity
- keep unrelated cleanup out of feature or bug-fix PRs
- update docs and examples when public behavior changes

Tests should prove observable behavior. For lifecycle, cancellation, metrics,
redirects, TLS, and resource-limit changes, assert on public state, errors, or
diagnostics where possible.

## Commit Messages

Use Conventional Commits:

```text
feat(client): add typed request options
fix(redirects): strip auth on cross-origin redirects
test(lifecycle): cover async cancellation cleanup
docs(tls): clarify custom CA trust mode
```

When a commit relates to a GitHub issue, reference it in the footer:

```text
fix(redirects): block scheme downgrade redirects

Refs #123
```

Use `Fixes #123` or `Closes #123` only when the commit fully closes the issue.

## Pull Request Checklist

Before requesting review, please check:

- the change has a focused scope
- related issues are linked
- Python tests pass
- Rust tests pass when Rust code changed
- pre-commit passes
- public API changes update types, docs, and examples
- security-sensitive behavior has regression tests
- new errors and diagnostics avoid leaking secrets
- limitations are documented honestly if the feature is partial

The project is small on purpose. A contribution that preserves that clarity is
usually easier to merge than a broad change that tries to solve several future
features at once.
