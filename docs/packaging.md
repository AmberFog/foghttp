# Packaging And Python Compatibility

FogHTTP ships a Rust extension built with PyO3. Published CPython wheels target
the stable `cp311-abi3` ABI, matching the package minimum of Python 3.11. One
wheel per supported operating-system and architecture pair covers the
currently validated GIL-enabled CPython 3.11-3.14 range instead of requiring a
separate wheel for every supported CPython minor version. The ABI may remain
compatible with newer Python versions, but FogHTTP does not claim that support
until the full suite and exact wheel pass the release validation matrix.

## Release Matrix

The release workflow builds these wheel artifacts once per release:

| Platform | Architectures | Install smoke |
|---|---|---|
| Linux (`manylinux2014`) | `x86_64`, `aarch64` | The `x86_64` wheel is installed on CPython 3.11-3.14; `aarch64` is cross-built and ABI-audited |
| macOS | `x86_64`, `aarch64` | Each wheel is installed on CPython 3.11-3.14 on its native runner |
| Windows | `x64` | The wheel is installed on CPython 3.11-3.14 |

A source distribution is published alongside the wheels. The supported
OS/architecture set is independent from the stable-ABI decision.

## Trade-offs

The stable ABI reduces native release compilations from twenty to five and
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
`abi3audit --strict`, and installs that exact artifact on CPython 3.11-3.14.
The release workflow repeats the ABI audit for every platform wheel and runs
the install smoke described above. The smoke exercises imports, URL handling,
and real sync and async requests against a local HTTP server. Native builds use
`Cargo.lock` with `maturin --locked` so Rust dependency resolution cannot drift
in CI or during a release.

Python versions newer than the currently tested 3.11-3.14 range may be ABI
compatible, but they are not part of the release compatibility claim until
they enter the CI matrix.

## Current Boundary

The current wheels target the classic `abi3` ABI for GIL-enabled CPython. That
ABI cannot be loaded by free-threaded CPython. PyO3 also supports the separate
`abi3t` stable ABI starting at Python 3.15, but adopting it requires its own
wheel strategy and validation matrix. FogHTTP does not publish `abi3t` wheels
today.
