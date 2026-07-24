# Cookies

FogHTTP cookies are client-level, opt-in session state. The default remains
stateless: `cookies=False` stores nothing and never adds a `Cookie` header.

```python
import foghttp


with foghttp.Client(cookies=True) as client:
    login = client.post(
        "https://api.example.com/login",
        json={"username": "ada", "password": "secret"},  # pragma: allowlist secret
    )
    login.raise_for_status()

    profile = client.get("https://api.example.com/profile")
    profile.raise_for_status()
```

`AsyncClient(cookies=True)` has the same behavior. The jar belongs to one
client, is kept only in memory, and disappears with that client. Clients never
share cookie state implicitly.

## Matching And Storage

The Rust transport owns the jar because redirects, retries, and streaming
response headers are already managed there. Enabling cookies does not add a
Python callback to each request.

For every `Set-Cookie` response field, FogHTTP independently applies the
following rules:

- host-only and `Domain` cookies use HTTP cookie domain matching
- `Path` uses segment-boundary matching; a missing or relative value uses the
  request URL's default path
- `Max-Age` takes precedence over tolerant HTTP cookie-date `Expires` parsing;
  persistent lifetimes are capped at 400 days and expired cookies are removed
- `Secure` cookies are accepted and sent only for HTTPS or a trustworthy
  loopback origin
- an insecure origin cannot overwrite or delete a matching secure cookie
- `__Secure-` and `__Host-` name-prefix requirements are enforced
- malformed or rejected fields do not prevent valid sibling fields from being
  stored

Matching cookies are sent with longer paths first, then by creation order.
Cookie values are opaque: percent-looking octets are preserved exactly rather
than decoded or canonicalized. Cookie scope does not include the TCP port.

Response headers update the jar before redirect or retry handling, before a
buffered body is read, and before a streaming response is exposed. A cookie set
on a retryable response can therefore be used by the next attempt. A body read
failure does not roll back a valid `Set-Cookie` already received in the response
headers.

## Header Precedence And Redirects

FogHTTP removes only its own previously attached `Cookie` header and selects
again for every transport attempt and redirect hop. It never blindly forwards
a managed cookie from the source URL to the redirect target.

An explicit request, prepared-request, client-default, or auth-generated
`Cookie` header wins for that hop. FogHTTP does not merge the jar into an
explicit value. The existing redirect security policy preserves explicit
cookies for same-origin redirects and removes them for cross-origin redirects;
after removal, the jar may select cookies that independently match the target.

Because HTTP cookies are scoped by host/domain and path rather than port, a
cookie may be sent to another port on the same matching host. `Secure` still
prevents sending a secure cookie over an untrusted plain-HTTP destination.

## Capacity And Expiration

The in-memory jar is bounded:

- at most 4096 octets for the cookie name and value together
- at most 16 KiB for one `Set-Cookie` field
- at most 50 cookies per stored domain value
- at most 3000 cookies per client

Expired entries are removed first. When a domain limit is exceeded, non-secure
cookies are evicted before secure cookies; equal-priority cookies and global
overflow are ordered by least recent access. Servers must tolerate cookie
eviction, as required for interoperable HTTP cookie use.

## Redaction

`Cookie` and `Set-Cookie` values are available through the normal header API,
but their values are redacted from request, response, redirect-history, and
header `repr()` output. Telemetry does not record request or response header
values. The native jar has no public debug or inspection representation and
does not log rejected cookie contents.

## V1 Boundaries

The v1 jar is an HTTP service-client feature, not a browser cookie engine:

- no public-suffix list is applied; only accept `Domain` cookies from services
  you trust not to set an overly broad suffix
- `SameSite`, `Partitioned`, and browser third-party-cookie policy are not
  enforced because FogHTTP has no browser top-level-site context
- there is no persistent storage, public jar mutation/inspection API, or
  automatic sharing between clients

Use a browser automation stack when those browser security and privacy
semantics are part of the application contract.
