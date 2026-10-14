# Packaging And Python Compatibility

FogHTTP ships a Rust extension built with PyO3. Published CPython wheels target
the stable `cp311-abi3` ABI, matching the package minimum of Python 3.11. One
wheel per supported operating-system and architecture pair covers the
GIL-enabled CPython 3.11-3.15 validation matrix instead of requiring a
separate wheel for every supported CPython minor version. The ABI may remain
compatible with newer Python versions, but FogHTTP does not claim that support
until the full suite and exact wheel pass the release validation matrix.

Python 3.15 coverage is an unreleased source-branch change. Published 0.4.1
was validated on Python 3.11-3.14; adding CI coverage does not publish a release.

## Release Matrix

The release workflow builds these wheel artifacts once per release:

| Platform | Architectures | Install smoke |
|---|---|---|
| Linux (`manylinux2014`) | `x86_64`, `aarch64` | The `x86_64` wheel is installed on CPython 3.11-3.15; `aarch64` is cross-built and ABI-audited |
| macOS | `x86_64`, `aarch64` | Each wheel is installed on CPython 3.11-3.15 on its native runner |
| Windows | `x64` | The wheel is installed on CPython 3.11-3.15 |

A source distribution is published alongside the wheels. The supported
OS/architecture set is independent from the stable-ABI decision.

### Linux Dependency Floors

FogHTTP's own wheels keep their `manylinux2014` tag (glibc 2.17). Runtime
dependencies have their own platform requirements:

| CPython | orjson constraint | Linux binary dependency floor |
|---|---|---|
| 3.11-3.14 | `>=3.11,<4` | glibc 2.17, unchanged |
| 3.15 | `>=3.13,<4` | glibc 2.39 (`manylinux_2_39`) |

These floors apply to both Linux architectures. Python 3.15's newer orjson
wheels do not raise the floor for older interpreters. The chosen Python
distribution can have additional OS requirements. A successful smoke on a
modern runner is not native execution evidence for the oldest supported OS;
binary dependency resolution at the declared floor is checked separately.

## Trade-offs

The stable ABI reduces native release compilations from twenty-five to five and
tests compatibility against the artifact users will actually install. It also
constrains FogHTTP to PyO3's Python 3.11 Limited API surface. PyO3 cannot use
every CPython-version-specific API or optimization in this mode, so FogHTTP
does not treat abi3 itself as a performance improvement. Runtime performance
claims remain subject to the project's benchmark suite and measured evidence.

## Validation Policy

The `abi3-py311` feature is enabled in the normal Cargo dependency graph, not
only in the release command. Rust checks therefore reject use of a CPython API
outside PyO3's Python 3.11 Limited API surface before release.

Pull-request CI builds one Linux `cp311-abi3` wheel, audits it with
`abi3audit --strict`, and installs that exact artifact on CPython 3.11-3.15.
The release workflow repeats the ABI audit for every platform wheel and runs
the install smoke described above. The smoke exercises imports, URL handling,
every top-level `examples/*.py` file under a non-`__main__` module name, and real
sync and async requests against a local HTTP server. Example imports use the
installed wheel and do not make outbound network requests. Native builds use
`Cargo.lock` with `maturin --locked` so Rust dependency resolution cannot drift
in CI or during a release.

Full-suite jobs select the matrix interpreter explicitly and consume `uv.lock`
with `uv --locked`; coverage remains on Python 3.14 with a 98% floor. Wheel
smoke instead uses ordinary pip resolution from package metadata and requires
binary dependencies, so an implicit source build cannot hide a missing wheel.

Before publishing, the release-readiness record also captures the installed-
wheel example smoke runs and the bounded benchmark smoke evidence defined in
[benchmarks.md](./benchmarks.md).

Python versions newer than the 3.11-3.15 validation matrix may be ABI
compatible, but they are not part of the release compatibility claim until
they enter the CI matrix.

## Current Boundary

The current wheels target the classic `abi3` ABI for GIL-enabled CPython. That
ABI cannot be loaded by free-threaded CPython. PyO3 also supports the separate
`abi3t` stable ABI starting at Python 3.15, but adopting it requires its own
wheel strategy and validation matrix. FogHTTP does not publish `abi3t` wheels
today.
