# SSRF Protection

FogHTTP provides an opt-in `SSRFPolicy` for service clients that accept URLs
from users, webhooks, feeds, callbacks, or other partially trusted sources. The
policy is disabled by default because a general-purpose HTTP client cannot know
which destinations an application intends to trust.

Enable the default public-network guard on either client:

```python
import foghttp


client = foghttp.Client(ssrf=foghttp.SSRFPolicy())
async_client = foghttp.AsyncClient(ssrf=foghttp.SSRFPolicy())
```

The default policy accepts HTTP and HTTPS destinations, then rejects IP
addresses that are private, loopback, link-local, multicast, cloud metadata,
unspecified, or otherwise reserved for common special-use networks. IPv4,
IPv6, IPv4-mapped IPv6, and common IPv4-embedding transition forms are
checked.

IPv6 destinations are accepted only from IANA-allocated global-unicast
prefixes or the globally reachable well-known NAT64 prefix. The list is
conservative: a newly allocated prefix remains blocked until FogHTTP updates
its registry snapshot.

## Destination Allowlists

Use scheme, exact-origin, and domain allowlists to narrow a service client:

```python
policy = foghttp.SSRFPolicy(
    allowed_schemes=("https",),
    allowed_origins=("https://api.example.com",),
    allowed_domains=("downloads.example.org",),
)

client = foghttp.Client(ssrf=policy)
```

The rules are:

- `allowed_schemes` defaults to `http` and `https` and may narrow the client to
  either scheme.
- If both destination lists are empty, any destination with a permitted scheme
  may proceed to IP validation.
- If `allowed_origins` or `allowed_domains` is non-empty, a destination must
  match at least one entry.
- Origins match the normalized scheme, host, and effective port exactly.
- String origins must use an explicit `http://` or `https://` authority and may
  contain only an optional trailing slash. Empty ports, dot-segment paths,
  control characters, query strings, and fragments are rejected rather than
  normalized into an allowlist entry. IP literals must use unambiguous IPv4
  dotted-decimal or bracketed IPv6 syntax; integer, hexadecimal, octal, short,
  and mixed numeric IPv4 forms are rejected.
- A domain entry matches the domain itself and its subdomains on label
  boundaries. Entries use normalized DNS-label syntax; wildcard syntax,
  URL escapes, ports, paths, and IP literals are rejected.
- All DNS names remain subject to post-resolution IP validation, including
  names listed in `allowed_origins` or `allowed_domains`.

An exact origin containing an IP literal is the only explicit exception to the
non-public-address rule. This supports a client dedicated to one trusted
internal endpoint without enabling an unrestricted private-network bypass:

```python
internal = foghttp.SSRFPolicy(
    allowed_schemes=("https",),
    allowed_origins=("https://10.20.30.40:8443",),
)
```

Do not build that allowlist from request data. Treat it as trusted application
configuration. Metadata, multicast, unspecified, and reserved special-use
addresses remain blocked even when listed as an exact origin.

## Redirect And DNS Enforcement

FogHTTP evaluates the destination policy before the initial request and before
every followed redirect hop. A redirect cannot escape the client-level
allowlist or switch to a blocked address.

For DNS names, the Rust resolver checks every returned address. The exact
validated address set is then passed to the connector, so the connector does
not perform a second lookup between validation and TCP connect. Each new DNS
resolution is checked again; a later answer that changes to a blocked address
is rejected. A pooled connection may reuse the endpoint that was already
validated when that connection was opened.

Proxy routes fail closed while `SSRFPolicy` is enabled. HTTP forward proxies
and HTTPS `CONNECT` proxies may resolve the target remotely, so the client
cannot prove that the checked local DNS result is the address used by the
proxy. Use network-layer egress controls when a protected workload must also
use a proxy.

## Errors And Privacy

A rejected request raises `RequestError` with an `SSRF policy blocked target`
message. Diagnostics include only a normalized URL origin or DNS hostname;
userinfo, paths, query parameters, fragments, and resolved IP details are not
included.

The policy is an application-layer guard, not a replacement for firewall,
service-mesh, container, or cloud egress policy. Defense in depth remains
necessary for workloads that process attacker-controlled URLs. In particular,
network-specific NAT64 or other translation prefixes cannot be inferred
generically from a destination address; deployments that expose such
translators must enforce their reachable IPv4 ranges at the egress boundary.
See the
[OWASP SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
for the broader threat model. Address classification follows the IANA
[IPv4 special-purpose](https://www.iana.org/assignments/iana-ipv4-special-registry/iana-ipv4-special-registry.xhtml),
[IPv6 special-purpose](https://www.iana.org/assignments/iana-ipv6-special-registry/iana-ipv6-special-registry.xhtml),
and [IPv6 global-unicast](https://www.iana.org/assignments/ipv6-unicast-address-assignments/ipv6-unicast-address-assignments.xhtml)
registries.
