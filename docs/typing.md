# Public Typing Contracts

FogHTTP provides structural typing contracts for application integrations that
consume requests and responses without depending on FogHTTP's concrete runtime
classes. Import these protocols from `foghttp.types`:

```python
from foghttp.types import ResponseProtocol


def response_summary(response: ResponseProtocol) -> str:
    return f"{response.request.method} {response.status_code}"
```

Concrete `Request`, `RequestInfo`, `Response`, `StreamResponse`, and
`AsyncStreamResponse` objects satisfy the applicable protocols without
inheriting from them.

Client wrappers can also import `HttpVersion` and `HttpVersions` from
`foghttp.types`. The current literal domain contains only `"HTTP/1.1"`, matching
the explicit `Client` and `AsyncClient` `http_versions=` option; HTTP/2 is not
implemented.

## Request And Response Protocols

| Protocol | Stable surface |
|---|---|
| `RequestProtocol` | Method, URL, headers, and immutable request extensions shared by prepared requests and completed request metadata. |
| `ResponseProtocol` | Metadata, status flags, redirect history, retry trace, encoding, and `raise_for_status()` shared by buffered and streaming responses. |
| `BufferedResponseProtocol` | `ResponseProtocol` plus buffered `content`, `text`, and `json()`. |
| `StreamResponseProtocol` | `ResponseProtocol` plus synchronous bytes, text, and line iterators and `close()`. |
| `AsyncStreamResponseProtocol` | `ResponseProtocol` plus asynchronous bytes, text, and line iterators, `close()`, and `aclose()`. |

`RequestProtocol` intentionally excludes request-body state. Buffered bytes,
direct streams, files, and replayable factories have different ownership and
replayability rules; use the provider contracts in
[Upload typing contracts](./upload-types.md) for request bodies.

The streaming protocols describe an already-entered response. The context
manager returned by `Client.stream()` or `AsyncClient.stream()` remains the
owner of response-body cleanup. See [Response streaming](./streaming.md).

## Hook And Policy Contracts

FogHTTP's stable callback surfaces are available at the package root:

| Contract | Meaning |
|---|---|
| `AuthHook` and `AuthRequest` | Synchronous request-aware authentication. |
| `TelemetryEventSink` and `TelemetryEvent` | Structural event-sink protocol and immutable telemetry event. |
| `TransportPolicyRequestHook` | Synchronous request policy callback. |
| `TransportPolicyResponseHook` | Synchronous response-head policy callback. |
| `TransportPolicyHooks` | Configuration that assigns the policy callbacks to lifecycle stages. |

Request, response, auth, and policy contracts may expose full URLs or headers.
They are trusted application inputs, not telemetry-safe payloads. Do not copy
them directly into logs, metrics, or traces. Use `TelemetryEvent` when an
integration needs redacted observability data.

## Stability Boundary

These protocols are static typing contracts. They are not decorated with
`runtime_checkable`, so do not use them with `isinstance()` or `issubclass()`.
Static structural typing checks method signatures as well as attribute names;
runtime protocol checks would only test attribute presence.

The public protocols do not expose raw clients, connectors, sockets, permits,
request-body replayability flags, cancellation handles, PyO3 bridge objects, or
the private transport adapter protocols. Those remain implementation details
and are not extension points.

This API is additive. Existing annotations that use concrete FogHTTP classes
remain valid; migrate to a protocol only when an integration accepts compatible
wrappers, fakes, or multiple FogHTTP response modes.

FogHTTP checks its public typing examples with strict mypy:

```bash
uv run --extra dev mypy --no-incremental
```
