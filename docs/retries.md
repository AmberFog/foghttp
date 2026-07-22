# Retry Policy

FogHTTP provides an opt-in, client-level retry policy for transient response
statuses and network failures before response headers arrive. The default
client does not enable this policy.

```python
import foghttp


retry = foghttp.RetryPolicy(
    retries=2,
    backoff=0.1,
    jitter=0.1,
)

with foghttp.Client(retry=retry) as client:
    response = client.get("https://api.example.com/items")
```

`retries` is the number of additional sends allowed by retry decisions across
one logical request. With no redirects, a policy with `retries=2` can therefore
make at most three attempts; redirect hops are bounded separately by
`max_redirects`. The same policy contract is available on `Client` and
`AsyncClient`, including buffered and streaming response entry points. For a
streaming response, retries finish before the response object is exposed;
failures while the caller consumes the returned response body are not retried.

## Defaults

`RetryPolicy()` uses these defaults:

| Option | Default | Meaning |
|---|---:|---|
| `retries` | `2` | Additional attempts after the initial send. |
| `backoff` | `0.1` | Base exponential delay in seconds. |
| `jitter` | `0.1` | Maximum random delay added to each backoff, in seconds. |
| `retry_on.statuses` | `429`, `502`, `503`, `504` | Response statuses eligible for retry. |
| `retry_on.exceptions` | `NetworkError` | Pre-header transport failure eligible for retry. |
| `methods` | `GET`, `HEAD`, `OPTIONS`, `QUERY`, `TRACE` | Methods eligible for automatic retry. |

The delay before retry number `n`, starting at zero, is
`backoff * 2**n + uniform(0, jitter)`. A valid `Retry-After` delta or HTTP date
on a retryable response is honored as a minimum delay. Backoff and response
draining remain inside the request's shared `Timeouts.total` budget, including
any redirect hops in the same logical request. Malformed `Retry-After` values
are ignored, and accepted server delays are capped by the same duration ceiling
as local numeric options.

`RetryConditions` makes triggers explicit:

```python
conditions = foghttp.RetryConditions(
    statuses=(429, 503),
    exceptions=(foghttp.NetworkError,),
)

retry = foghttp.RetryPolicy(
    retries=3,
    backoff=0.2,
    jitter=0.05,
    retry_on=conditions,
)
```

Use an empty tuple to disable a trigger category. The current exception
contract supports `NetworkError` only; local upload-provider failures and
FogHTTP timeout exceptions are not classified as retryable network failures.
Response-body failures after headers are also not retried.

## Method And Body Safety

`POST` is deliberately absent from the default method set. This prevents an
automatic retry from duplicating a side effect. Applications can explicitly
replace `methods`, but they then own the endpoint's idempotency guarantee:

```python
retry = foghttp.RetryPolicy(methods=("GET", "PUT", "POST"))
```

Method eligibility is necessary but not sufficient. A non-empty request body
must also be replayable:

| Body source | Replayable |
|---|---|
| `bytes`, `str`, `json=`, encoded `data=` | Yes |
| bytes-like multipart parts | Yes |
| zero-argument stream or multipart factory | Yes, if it returns equivalent fresh content |
| direct iterator, async iterator, or file-like `content=` | No |
| direct file or stream multipart part | No |

RFC 10008 classifies `QUERY` as safe and idempotent, so it is enabled by
default. A body-bearing QUERY is still retried only when its provider is
replayable. If a matching response or network failure occurs with a
non-replayable body, FogHTTP returns the response or raises the original error
without a second send and records `block_non_replayable` with reason
`non_replayable_body`.

There is no public `body_replayable=True` escape hatch. Use a zero-argument
factory when a stream can be recreated safely for every attempt.

## Ordering And Resources

Retry runs inside the Rust transport policy pipeline. Redirect classification
has priority for a response that is both a redirect and listed in retry
statuses. Each new retry attempt reruns route selection and lightweight
`before_send`/`on_response_headers` policy hooks.

Before retrying a status response, FogHTTP drains its body under the configured
read and total deadlines. A clean keep-alive connection can then return to the
pool. A connection that fails before headers is not reused. The request slot is
released before backoff, so sleeping retries do not occupy active transport
capacity. Cancelling an async request cancels its pending backoff and releases
the logical request lifecycle.

## Observability

A request made by a client with `RetryPolicy` exposes one immutable,
request-scoped `RetryTrace` when transport execution returns a buffered or
streaming response, or raises a terminal `FogHTTPError`. Responses provide it
as `response.retry_trace`; terminal `FogHTTPError` instances provide the same
property. Errors raised before native transport execution are outside this
contract. A client without a retry policy returns `None`, so the default path
does not collect attempt history or allocate terminal trace values.

```python
try:
    response = client.get("https://api.example.com/items")
except foghttp.FogHTTPError as error:
    trace = error.retry_trace
else:
    trace = response.retry_trace

if trace is not None:
    for attempt in trace.attempts:
        print(attempt.attempt, attempt.decision, attempt.reason)
```

`RetryTrace` contains:

| Field | Meaning |
|---|---|
| `attempts` | Ordered immutable tuple, bounded to at most `retries + 1` entries. |
| `outcome` | `response` when the transport returned a response object, or `error` when it raised. |
| `status_code` | Final response status, otherwise `None`. |
| `error_type` | Final public exception class name, otherwise `None`. |
| `elapsed` | Total logical-request time in seconds through the returned response or error. |

Each `RetryAttempt` contains the 1-based `attempt`, normalized `method`,
credential-free `origin`, zero-based `redirect_hop`, optional `status_code` and
`error_type`, typed `decision` and `reason`, selected `backoff` in seconds,
optional cumulative `decision_elapsed` seconds when the retry decision was
committed by the transport, and cumulative `completed_elapsed` seconds when the
transport attempt completed. A buffered attempt can contain both a status and
a later body-read error. The final physical transport attempt is always
present. Its
`decision` and `reason` are `None` when that attempt did not trigger retry
policy; a terminal method stop, replayability block or exhaustion retains its
typed decision and reason.

A logical request can fail after its latest transport attempt has completed.
For example, a total timeout during retry backoff is reported by
`RetryTrace.error_type` and `RetryTrace.elapsed`; it does not overwrite the
completed status or network result of the preceding attempt.

`RetryTraceOutcome.RESPONSE` means that request execution produced a response;
it does not classify an HTTP status as successful. For streaming responses the
trace is complete when response headers are exposed, because body-consumption
failures are outside the retry scope and do not mutate the immutable trace.
`HTTPStatusError` preserves the trace of its response.

FogHTTP preserves the original terminal request error if CPython cannot
allocate or attach the native trace handoff object. That exceptional attachment
failure is reported through `sys.unraisablehook`; the error then has no trace
rather than being replaced by an observability error.

Trace values never include a request path, query, headers, body, credentials or
userinfo. They retain only the normalized origin and typed operational fields,
so their default representation is safe for diagnostics.

When telemetry is enabled and the native request returns or raises, each retry
decision emits a typed `TelemetryEventType.RETRY_DECISION` event with:

- `retry_attempt`, starting at `1` for the failed initial attempt;
- `status_code` or `error_type`;
- `retry_decision`: `retry`, `stop`, or `block_non_replayable`;
- `retry_reason`: `status`, `network_error`, `method_not_allowed`,
  `non_replayable_body`, or `retries_exhausted`;
- `retry_backoff_ns` and `elapsed_ns`;
- normalized method and origin, without request path, query, headers, or body.

The public trace and telemetry events are derived from the same native attempt
records; terminal attempts without a retry decision do not emit a
`retry_decision` event. The final `request_finished` event still reports the
logical request outcome. Native records are delivered when the transport
returns or raises, not as live callbacks during backoff.
`RetryAttempt.decision` and `RetryAttempt.reason` intentionally reuse
`TelemetryRetryDecision` and `TelemetryRetryReason` as the shared public retry
vocabulary; telemetry is a projection of the same decision records rather than
a separate enum contract.
For a `retry_decision` event, `elapsed_ns` is derived from
`RetryAttempt.decision_elapsed`, and `status_code`/`error_type` describe the
trigger seen when that decision was committed. A later buffered-body error can
therefore appear on the state-oriented `RetryAttempt` without rewriting the
earlier decision event.

Cancelling an async caller can abort the native task before a response or
exception is returned. `asyncio.CancelledError` therefore does not manufacture
a partial `retry_trace`, and buffered retry decisions, including the decision
that selected a cancelled backoff, are not emitted to the Python sink. There is
no global retry-trace history.
