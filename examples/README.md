# FogHTTP Examples

These examples focus on workloads where FogHTTP already works well, including
reusable `base_url` clients, default headers, and default query params for
one-upstream APIs. They also show the current request builder contract and
prepared request flow.

The examples use public `httpbin.org` endpoints, so they require outbound
network access. Run them from the repository root after building the local
extension:

```bash
uv run --with "maturin>=1.7,<2" maturin develop
uv run examples/sync_json_api.py
uv run examples/sync_streaming.py
uv run examples/async_json_fanout.py
uv run examples/async_resource_limits.py
uv run examples/async_lifecycle_debug.py
uv run examples/async_streaming.py
uv run examples/compressed_response.py
uv run examples/http_proxy.py
uv run examples/multipart_uploads.py
uv run examples/redirects.py
uv run examples/prepared_requests.py
uv run examples/request_builder_compatibility.py
uv run examples/retry_policy.py
uv run examples/ssrf_policy.py
uv run examples/telemetry_hooks.py
```

## Good Examples

- [sync_json_api.py](./sync_json_api.py): sync JSON request/response flow.
- [sync_streaming.py](./sync_streaming.py): sync bytes, text, and line response
  streaming with explicit context-managed cleanup.
- [async_json_fanout.py](./async_json_fanout.py): concurrent async GET requests
  with global/per-origin active request limits and stats.
- [async_resource_limits.py](./async_resource_limits.py): explicit global and
  per-origin request backpressure with expected pool-timeout handling and
  diagnostics.
- [async_lifecycle_debug.py](./async_lifecycle_debug.py): opt-in async lifecycle
  debug snapshots and strict no-leak assertion pattern.
- [async_streaming.py](./async_streaming.py): async bytes, text, and line response
  streaming with explicit context-managed cleanup.
- [compressed_response.py](./compressed_response.py): manual
  `Accept-Encoding` negotiation with transparent buffered response decoding.
- [http_proxy.py](./http_proxy.py): direct request by default, or HTTP proxy
  routing / HTTPS `CONNECT` tunnelling with
  `FOGHTTP_HTTP_PROXY=http://proxy:port`; set `FOGHTTP_PROXY_TARGET_URL` to
  choose the target URL.
- [multipart_uploads.py](./multipart_uploads.py): multipart `files=` uploads
  with direct file objects and replayable stream factories.
- [redirects.py](./redirects.py): GET and POST redirects, final URL, and
  history.
- [prepared_requests.py](./prepared_requests.py): build, inspect, adjust, and
  send prepared requests.
- [request_builder_compatibility.py](./request_builder_compatibility.py):
  client defaults, repeated query params, form data, prepared requests, and body
  conflict validation.
- [retry_policy.py](./retry_policy.py): opt-in status retries and immutable
  request-scoped attempt trace inspection.
- [ssrf_policy.py](./ssrf_policy.py): a trusted domain allowlist and stable
  typed rejection reason for a blocked destination.
- [telemetry_hooks.py](./telemetry_hooks.py): opt-in typed telemetry events with
  redacted URLs and explicit hook error policy.

## Limitations To Keep In Mind

FogHTTP supports sync and async response streaming for bytes, text, and lines,
plus plain HTTP proxy routing and HTTPS proxy `CONNECT` through `http://` proxy
endpoints. Streaming request uploads and multipart `files=` uploads are
available. Do not use these examples as templates for cookie sessions,
SOCKS/PAC proxy clients, TLS-to-proxy endpoints, or streaming decompression yet.
