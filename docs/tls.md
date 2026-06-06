# TLS Trust

FogHTTP verifies HTTPS certificates by default. There is no `verify=False`
mode because disabling certificate verification creates a silent production
security footgun. Use explicit trust roots instead.

## Trust Modes

| Mode | Configuration | Trust boundary |
|---|---|---|
| Default WebPKI | `foghttp.Client()` | Bundled WebPKI roots only |
| WebPKI plus custom CA | `TLSConfig(ca_certificates=(...))` | Bundled WebPKI roots plus explicit CA files |
| Custom-only CA | `TLSConfig(ca_certificates=(...), trust_webpki_roots=False)` | Explicit CA files only |

## Default Trust

By default FogHTTP trusts the bundled WebPKI root store used by the Rust
transport.

```python
import foghttp


with foghttp.Client() as client:
    response = client.get("https://api.example.com/health")
    response.raise_for_status()
```

This mode is intended for public HTTPS endpoints whose certificates chain to
public WebPKI roots.

## WebPKI Plus Custom CA

For private services that use an internal CA, pass CA certificate files through
`TLSConfig`. By default these certificates are added to the WebPKI root store.

```python
from pathlib import Path

import foghttp


tls = foghttp.TLSConfig(
    ca_certificates=(Path("/etc/company/ca.pem"),),
)

with foghttp.Client(tls=tls) as client:
    response = client.get("https://internal-api.example.com/health")
    response.raise_for_status()
```

Use this when the client talks to both public HTTPS endpoints and internal
endpoints signed by a private CA.

## Custom-Only CA

For tighter enterprise trust boundaries, disable WebPKI roots and provide one
or more custom CA certificate files.

```python
from pathlib import Path

import foghttp


tls = foghttp.TLSConfig(
    ca_certificates=(Path("/etc/company/ca.pem"),),
    trust_webpki_roots=False,
)

with foghttp.Client(tls=tls) as client:
    response = client.get("https://internal-api.example.com/health")
    response.raise_for_status()
```

This mode trusts only the CA files you pass. `TLSConfig` rejects
`trust_webpki_roots=False` without custom CA certificates so the transport
cannot accidentally run with an empty or verification-free trust boundary.

Use custom-only trust when the client must reject public WebPKI chains and trust
only an internal or regulated CA bundle.

## Native Roots And Environment

FogHTTP does not load operating-system trust stores today. With
`trust_env=True`, `SSL_CERT_FILE` is mapped to
`TLSConfig(ca_certificates=(...))` only when no explicit `tls=` is passed.
The environment path is snapshotted at client config creation; the certificate
file is read and validated later, when the Rust transport is created.
`SSL_CERT_DIR` and environment-driven TLS verification disabling are not used.
The active trust boundary is always explicit `TLSConfig`, env-derived
`SSL_CERT_FILE`, and bundled WebPKI roots when `trust_webpki_roots=True`.

## Unsupported Unsafe Modes

FogHTTP intentionally does not expose a `verify=False` compatibility switch.
Certificate or SPKI pinning is not implemented yet; use custom-only CA trust for
internal trust replacement until a dedicated pinning API exists.

## Current Boundaries

- Custom certificates must be PEM files containing CA certificates.
- Certificate files are read when the Rust transport is created.
- The same `TLSConfig` works with `Client` and `AsyncClient`.
- Operating-system trust stores are not used today.
- `trust_env=True` supports `SSL_CERT_FILE` and plain HTTP proxy routing;
  proxied HTTPS targets fail closed until HTTPS proxy `CONNECT` is implemented.
- Disabling certificate verification is intentionally not supported.
