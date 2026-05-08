# FogHTTP Examples

These examples focus on workloads where FogHTTP already works well.

Run them from the repository root after building the local extension:

```bash
uv run maturin develop
uv run examples/sync_json_api.py
uv run examples/async_json_fanout.py
uv run examples/redirects.py
```

## Good Examples

- [sync_json_api.py](./sync_json_api.py): sync JSON request/response flow.
- [async_json_fanout.py](./async_json_fanout.py): concurrent async GET requests
  with connection limits and stats.
- [redirects.py](./redirects.py): GET and POST redirects, final URL, and
  history.

## Limitations To Keep In Mind

FogHTTP is currently buffered. Do not use these examples as templates for large
downloads, large uploads, multipart forms, cookie sessions, proxy-heavy clients,
or streaming APIs yet.
