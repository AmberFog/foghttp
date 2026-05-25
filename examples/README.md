# FogHTTP Examples

These examples focus on workloads where FogHTTP already works well, including
reusable `base_url` clients, default headers, and default query params for
one-upstream APIs. They also show the current request builder contract and
prepared request flow.

Run them from the repository root after building the local extension:

```bash
uv run --with "maturin>=1.7,<2" maturin develop
uv run examples/sync_json_api.py
uv run examples/sync_streaming.py
uv run examples/async_json_fanout.py
uv run examples/async_resource_limits.py
uv run examples/async_streaming.py
uv run examples/compressed_response.py
uv run examples/redirects.py
uv run examples/prepared_requests.py
uv run examples/request_builder_compatibility.py
```

## Good Examples

- [sync_json_api.py](./sync_json_api.py): sync JSON request/response flow.
- [sync_streaming.py](./sync_streaming.py): sync bytes-first response streaming
  with explicit context-managed cleanup.
- [async_json_fanout.py](./async_json_fanout.py): concurrent async GET requests
  with global/per-origin active request limits and stats.
- [async_resource_limits.py](./async_resource_limits.py): explicit global and
  per-origin request backpressure with pool timeout settings and diagnostics.
- [async_streaming.py](./async_streaming.py): async bytes-first response
  streaming with explicit context-managed cleanup.
- [compressed_response.py](./compressed_response.py): manual
  `Accept-Encoding` negotiation with transparent buffered response decoding.
- [redirects.py](./redirects.py): GET and POST redirects, final URL, and
  history.
- [prepared_requests.py](./prepared_requests.py): build, inspect, adjust, and
  send prepared requests.
- [request_builder_compatibility.py](./request_builder_compatibility.py):
  client defaults, repeated query params, form data, prepared requests, and body
  conflict validation.

## Limitations To Keep In Mind

FogHTTP supports sync and async response byte streaming, but uploads are still
buffered. Do not use these examples as templates for large uploads, multipart
forms, cookie sessions, proxy-heavy clients, or text/line streaming APIs yet.
