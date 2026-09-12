use crate::core::url::HttpUrl;
use std::collections::HashSet;
use std::error::Error;
use std::fmt::{Display, Formatter};
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};

const SUPPORTED_SCHEMES: [&str; 2] = ["http", "https"];
const IPV4_PCP_ANYCAST: Ipv4Addr = Ipv4Addr::new(192, 0, 0, 9);
const IPV4_TURN_ANYCAST: Ipv4Addr = Ipv4Addr::new(192, 0, 0, 10);
const IPV6_METADATA: Ipv6Addr = Ipv6Addr::new(0xfd00, 0x0ec2, 0, 0, 0, 0, 0, 0x0254);
const IPV6_COMPATIBLE: Ipv6Addr = Ipv6Addr::UNSPECIFIED;
const IPV6_NAT64_WELL_KNOWN: Ipv6Addr = Ipv6Addr::new(0x0064, 0xff9b, 0, 0, 0, 0, 0, 0);
const IPV6_IETF_PROTOCOL_ASSIGNMENTS: Ipv6Addr = Ipv6Addr::new(0x2001, 0, 0, 0, 0, 0, 0, 0);
const IPV6_PCP_ANYCAST: Ipv6Addr = Ipv6Addr::new(0x2001, 1, 0, 0, 0, 0, 0, 1);
const IPV6_TURN_ANYCAST: Ipv6Addr = Ipv6Addr::new(0x2001, 1, 0, 0, 0, 0, 0, 2);
const IPV6_DNSSD_ANYCAST: Ipv6Addr = Ipv6Addr::new(0x2001, 1, 0, 0, 0, 0, 0, 3);
const IPV6_AMT: Ipv6Addr = Ipv6Addr::new(0x2001, 3, 0, 0, 0, 0, 0, 0);
const IPV6_AS112: Ipv6Addr = Ipv6Addr::new(0x2001, 4, 0x0112, 0, 0, 0, 0, 0);
const IPV6_ORCHID_V2: Ipv6Addr = Ipv6Addr::new(0x2001, 0x0020, 0, 0, 0, 0, 0, 0);
const IPV6_DET: Ipv6Addr = Ipv6Addr::new(0x2001, 0x0030, 0, 0, 0, 0, 0, 0);
const IPV6_DOCUMENTATION: Ipv6Addr = Ipv6Addr::new(0x2001, 0x0db8, 0, 0, 0, 0, 0, 0);
const IPV6_6TO4: Ipv6Addr = Ipv6Addr::new(0x2002, 0, 0, 0, 0, 0, 0, 0);

// Registry snapshot audited on 2026-07-23 against the IANA IPv4/IPv6
// Special-Purpose registries (updated 2025-10-09) and IPv6 Global Unicast
// registry (updated 2025-10-10). When the registries change, update this
// table, the special-use exceptions above, and the classification tests
// together. Unlisted global-unicast space remains blocked fail-closed.
// Sources: https://www.iana.org/assignments/iana-ipv4-special-registry/,
// https://www.iana.org/assignments/iana-ipv6-special-registry/, and
// https://www.iana.org/assignments/ipv6-unicast-address-assignments/.
const IPV6_ALLOCATED_GLOBAL_UNICAST: [(Ipv6Addr, u32); 22] = [
    (Ipv6Addr::new(0x2001, 0, 0, 0, 0, 0, 0, 0), 20),
    (Ipv6Addr::new(0x2001, 0x1200, 0, 0, 0, 0, 0, 0), 23),
    (Ipv6Addr::new(0x2001, 0x1400, 0, 0, 0, 0, 0, 0), 22),
    (Ipv6Addr::new(0x2001, 0x1800, 0, 0, 0, 0, 0, 0), 21),
    (Ipv6Addr::new(0x2001, 0x2000, 0, 0, 0, 0, 0, 0), 19),
    (Ipv6Addr::new(0x2001, 0x4000, 0, 0, 0, 0, 0, 0), 21),
    (Ipv6Addr::new(0x2001, 0x4800, 0, 0, 0, 0, 0, 0), 22),
    (Ipv6Addr::new(0x2001, 0x4c00, 0, 0, 0, 0, 0, 0), 23),
    (Ipv6Addr::new(0x2001, 0x5000, 0, 0, 0, 0, 0, 0), 20),
    (Ipv6Addr::new(0x2001, 0x8000, 0, 0, 0, 0, 0, 0), 18),
    (Ipv6Addr::new(0x2002, 0, 0, 0, 0, 0, 0, 0), 16),
    (Ipv6Addr::new(0x2003, 0, 0, 0, 0, 0, 0, 0), 18),
    (Ipv6Addr::new(0x2400, 0, 0, 0, 0, 0, 0, 0), 12),
    (Ipv6Addr::new(0x2410, 0, 0, 0, 0, 0, 0, 0), 12),
    (Ipv6Addr::new(0x2600, 0, 0, 0, 0, 0, 0, 0), 12),
    (Ipv6Addr::new(0x2610, 0, 0, 0, 0, 0, 0, 0), 23),
    (Ipv6Addr::new(0x2620, 0, 0, 0, 0, 0, 0, 0), 23),
    (Ipv6Addr::new(0x2630, 0, 0, 0, 0, 0, 0, 0), 12),
    (Ipv6Addr::new(0x2800, 0, 0, 0, 0, 0, 0, 0), 12),
    (Ipv6Addr::new(0x2a00, 0, 0, 0, 0, 0, 0, 0), 12),
    (Ipv6Addr::new(0x2a10, 0, 0, 0, 0, 0, 0, 0), 12),
    (Ipv6Addr::new(0x2c00, 0, 0, 0, 0, 0, 0, 0), 12),
];

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct SsrfPolicy {
    schemes: HashSet<String>,
    origins: HashSet<String>,
    domains: Vec<String>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum BlockedIpKind {
    LinkLocal,
    Loopback,
    Metadata,
    Multicast,
    Private,
    SpecialUse,
    Unspecified,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum SsrfViolationReason {
    DestinationNotAllowed,
    NonPublicAddress,
    ProxyResolutionUnsupported,
    SchemeNotAllowed,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct SsrfViolation {
    target: String,
    reason: SsrfViolationReason,
}

impl SsrfPolicy {
    pub(crate) fn new(
        allowed_schemes: Vec<String>,
        allowed_origins: Vec<String>,
        allowed_domains: Vec<String>,
    ) -> Result<Self, String> {
        let allowed_schemes = normalize_schemes(allowed_schemes)?;
        let allowed_origins = normalize_origins(allowed_origins, &allowed_schemes)?;
        let allowed_domains = normalize_domains(allowed_domains)?;
        Ok(Self {
            schemes: allowed_schemes,
            origins: allowed_origins,
            domains: allowed_domains,
        })
    }

    pub(crate) fn validate_url(&self, url: &HttpUrl) -> Result<(), SsrfViolation> {
        let origin = url.origin();
        if !self.schemes.contains(url.scheme()) {
            return Err(SsrfViolation::new(
                origin,
                SsrfViolationReason::SchemeNotAllowed,
            ));
        }

        let host = url.host();
        let origin_allowed = self.origins.contains(&origin);
        if self.has_destination_allowlist()
            && !origin_allowed
            && !self
                .domains
                .iter()
                .any(|domain| domain_matches(&host, domain))
        {
            return Err(SsrfViolation::new(
                origin,
                SsrfViolationReason::DestinationNotAllowed,
            ));
        }

        if let Ok(address) = host.parse::<IpAddr>() {
            let blocked = blocked_ip_kind(address);
            if origin_allowed
                && matches!(
                    blocked,
                    None | Some(
                        BlockedIpKind::Private | BlockedIpKind::Loopback | BlockedIpKind::LinkLocal
                    )
                )
            {
                return Ok(());
            }
            if blocked.is_some() {
                return Err(SsrfViolation::new(
                    origin,
                    SsrfViolationReason::NonPublicAddress,
                ));
            }
        }
        Ok(())
    }

    fn has_destination_allowlist(&self) -> bool {
        !self.origins.is_empty() || !self.domains.is_empty()
    }
}

impl SsrfViolation {
    pub(crate) fn proxy(origin: String) -> Self {
        Self::new(origin, SsrfViolationReason::ProxyResolutionUnsupported)
    }

    fn new(target: String, reason: SsrfViolationReason) -> Self {
        Self { target, reason }
    }

    pub(crate) const fn reason(&self) -> SsrfViolationReason {
        self.reason
    }
}

impl SsrfViolationReason {
    pub(crate) const fn as_code(self) -> &'static str {
        match self {
            Self::DestinationNotAllowed => "destination_not_allowed",
            Self::NonPublicAddress => "non_public_address",
            Self::ProxyResolutionUnsupported => "proxy_resolution_unsupported",
            Self::SchemeNotAllowed => "scheme_not_allowed",
        }
    }
}

pub(crate) fn validate_resolved_address(
    target: &str,
    address: IpAddr,
) -> Result<(), SsrfViolation> {
    if blocked_ip_kind(address).is_some() {
        return Err(SsrfViolation::new(
            target.to_owned(),
            SsrfViolationReason::NonPublicAddress,
        ));
    }
    Ok(())
}

impl Display for SsrfViolation {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(
            formatter,
            "SSRF policy blocked target '{}' ({})",
            self.target, self.reason
        )
    }
}

impl Error for SsrfViolation {}

impl Display for SsrfViolationReason {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(match self {
            Self::DestinationNotAllowed => "destination is not allowlisted",
            Self::NonPublicAddress => "address is not publicly routable",
            Self::ProxyResolutionUnsupported => {
                "proxy transport cannot guarantee local DNS validation"
            }
            Self::SchemeNotAllowed => "scheme is not allowlisted",
        })
    }
}

pub(crate) fn blocked_ip_kind(address: IpAddr) -> Option<BlockedIpKind> {
    match address.to_canonical() {
        IpAddr::V4(address) => blocked_ipv4_kind(address),
        IpAddr::V6(address) => blocked_ipv6_kind(address),
    }
}

fn blocked_ipv4_kind(address: Ipv4Addr) -> Option<BlockedIpKind> {
    if is_metadata_v4(address) {
        return Some(BlockedIpKind::Metadata);
    }
    if address.is_loopback() {
        return Some(BlockedIpKind::Loopback);
    }
    if address.is_private() {
        return Some(BlockedIpKind::Private);
    }
    if address.is_link_local() {
        return Some(BlockedIpKind::LinkLocal);
    }
    if address.is_multicast() {
        return Some(BlockedIpKind::Multicast);
    }
    if address.is_unspecified() {
        return Some(BlockedIpKind::Unspecified);
    }
    if is_special_use_v4(address) {
        return Some(BlockedIpKind::SpecialUse);
    }
    None
}

fn blocked_ipv6_kind(address: Ipv6Addr) -> Option<BlockedIpKind> {
    if is_metadata_v6(address) {
        return Some(BlockedIpKind::Metadata);
    }
    if address.is_loopback() {
        return Some(BlockedIpKind::Loopback);
    }
    if address.is_unique_local() {
        return Some(BlockedIpKind::Private);
    }
    if address.is_unicast_link_local() {
        return Some(BlockedIpKind::LinkLocal);
    }
    if address.is_multicast() {
        return Some(BlockedIpKind::Multicast);
    }
    if address.is_unspecified() {
        return Some(BlockedIpKind::Unspecified);
    }
    if let Some(embedded) = embedded_ipv4(address) {
        return blocked_ipv4_kind(embedded);
    }
    if is_special_use_v6(address) {
        return Some(BlockedIpKind::SpecialUse);
    }
    None
}

fn is_metadata_v4(address: Ipv4Addr) -> bool {
    matches!(
        address.octets(),
        [169, 254, 169, 254] | [169, 254, 170, 2] | [100, 100, 100, 200]
    )
}

fn is_metadata_v6(address: Ipv6Addr) -> bool {
    address == IPV6_METADATA
}

fn is_special_use_v4(address: Ipv4Addr) -> bool {
    ipv4_in_prefix(address, Ipv4Addr::UNSPECIFIED, 8)
        || ipv4_in_prefix(address, Ipv4Addr::new(100, 64, 0, 0), 10)
        || is_non_global_ietf_protocol_assignment_v4(address)
        || ipv4_in_prefix(address, Ipv4Addr::new(192, 0, 2, 0), 24)
        || ipv4_in_prefix(address, Ipv4Addr::new(192, 88, 99, 0), 24)
        || ipv4_in_prefix(address, Ipv4Addr::new(198, 18, 0, 0), 15)
        || ipv4_in_prefix(address, Ipv4Addr::new(198, 51, 100, 0), 24)
        || ipv4_in_prefix(address, Ipv4Addr::new(203, 0, 113, 0), 24)
        || ipv4_in_prefix(address, Ipv4Addr::new(240, 0, 0, 0), 4)
}

fn is_special_use_v6(address: Ipv6Addr) -> bool {
    !is_allocated_global_unicast_v6(address)
        || is_non_global_ietf_protocol_assignment(address)
        || ipv6_in_prefix(address, IPV6_DOCUMENTATION, 32)
        || ipv6_in_prefix(address, IPV6_6TO4, 16)
}

fn is_non_global_ietf_protocol_assignment_v4(address: Ipv4Addr) -> bool {
    ipv4_in_prefix(address, Ipv4Addr::new(192, 0, 0, 0), 24)
        && address != IPV4_PCP_ANYCAST
        && address != IPV4_TURN_ANYCAST
}

fn is_allocated_global_unicast_v6(address: Ipv6Addr) -> bool {
    ipv6_in_prefix(address, IPV6_NAT64_WELL_KNOWN, 96)
        || IPV6_ALLOCATED_GLOBAL_UNICAST
            .iter()
            .any(|(network, prefix)| ipv6_in_prefix(address, *network, *prefix))
}

fn is_non_global_ietf_protocol_assignment(address: Ipv6Addr) -> bool {
    ipv6_in_prefix(address, IPV6_IETF_PROTOCOL_ASSIGNMENTS, 23)
        && address != IPV6_PCP_ANYCAST
        && address != IPV6_TURN_ANYCAST
        && address != IPV6_DNSSD_ANYCAST
        && !ipv6_in_prefix(address, IPV6_AMT, 32)
        && !ipv6_in_prefix(address, IPV6_AS112, 48)
        && !ipv6_in_prefix(address, IPV6_ORCHID_V2, 28)
        && !ipv6_in_prefix(address, IPV6_DET, 28)
}

fn embedded_ipv4(address: Ipv6Addr) -> Option<Ipv4Addr> {
    if !ipv6_in_prefix(address, IPV6_COMPATIBLE, 96)
        && !ipv6_in_prefix(address, IPV6_NAT64_WELL_KNOWN, 96)
    {
        return None;
    }
    let octets = address.octets();
    Some(Ipv4Addr::new(
        octets[12], octets[13], octets[14], octets[15],
    ))
}

fn ipv4_in_prefix(address: Ipv4Addr, network: Ipv4Addr, prefix: u32) -> bool {
    let mask = u32::MAX.checked_shl(32 - prefix).unwrap_or(0);
    u32::from(address) & mask == u32::from(network) & mask
}

fn ipv6_in_prefix(address: Ipv6Addr, network: Ipv6Addr, prefix: u32) -> bool {
    let mask = u128::MAX.checked_shl(128 - prefix).unwrap_or(0);
    u128::from(address) & mask == u128::from(network) & mask
}

fn normalize_schemes(schemes: Vec<String>) -> Result<HashSet<String>, String> {
    let normalized = schemes
        .into_iter()
        .map(|scheme| {
            if scheme != scheme.trim() {
                return Err("SSRFPolicy.allowed_schemes contains surrounding whitespace".to_owned());
            }
            let scheme = scheme.to_ascii_lowercase();
            if !SUPPORTED_SCHEMES.contains(&scheme.as_str()) {
                return Err("SSRFPolicy.allowed_schemes supports only http and https".to_owned());
            }
            Ok(scheme)
        })
        .collect::<Result<HashSet<_>, _>>()?;
    if normalized.is_empty() {
        return Err("SSRFPolicy.allowed_schemes must not be empty".to_owned());
    }
    Ok(normalized)
}

fn normalize_origins(
    origins: Vec<String>,
    schemes: &HashSet<String>,
) -> Result<HashSet<String>, String> {
    origins
        .into_iter()
        .map(|origin| {
            if !is_strict_origin_input(&origin) {
                return Err(
                    "SSRFPolicy.allowed_origins must contain origin-only HTTP(S) URLs".to_owned(),
                );
            }
            let url = HttpUrl::parse(&origin)?;
            if !url.is_origin_only() || !has_unambiguous_ip_host(&origin, &url) {
                return Err(
                    "SSRFPolicy.allowed_origins must contain origin-only HTTP(S) URLs".to_owned(),
                );
            }
            if !schemes.contains(url.scheme()) {
                return Err("SSRFPolicy.allowed_origins contains a disabled scheme".to_owned());
            }
            Ok(url.origin())
        })
        .collect()
}

fn normalize_domains(domains: Vec<String>) -> Result<Vec<String>, String> {
    let mut normalized = domains
        .into_iter()
        .map(|domain| normalize_domain(&domain))
        .collect::<Result<Vec<_>, _>>()?;
    normalized.sort_unstable();
    normalized.dedup();
    Ok(normalized)
}

fn normalize_domain(domain: &str) -> Result<String, String> {
    if domain.is_empty()
        || domain != domain.trim()
        || contains_control_or_whitespace(domain)
        || domain.starts_with('.')
        || domain.ends_with('.')
        || domain
            .chars()
            .any(|character| ":/?#@[]*%\\".contains(character))
    {
        return Err("SSRFPolicy.allowed_domains contains an invalid domain".to_owned());
    }
    let url = HttpUrl::parse(&format!("http://{domain}"))?;
    let host = url.host();
    if host.parse::<IpAddr>().is_ok() {
        return Err("SSRFPolicy.allowed_domains must not contain IP addresses".to_owned());
    }
    if !is_valid_domain(&host) {
        return Err("SSRFPolicy.allowed_domains contains an invalid domain".to_owned());
    }
    Ok(host)
}

fn is_strict_origin_input(origin: &str) -> bool {
    if origin != origin.trim()
        || contains_control_or_whitespace(origin)
        || origin.chars().any(|character| "%\\@?#".contains(character))
    {
        return false;
    }
    let Some((scheme, authority_and_path)) = origin.split_once("://") else {
        return false;
    };
    if scheme.is_empty() || authority_and_path.is_empty() {
        return false;
    }
    let authority = authority_and_path
        .strip_suffix('/')
        .unwrap_or(authority_and_path);
    !authority.is_empty() && !authority.contains('/') && !authority.ends_with(':')
}

fn contains_control_or_whitespace(value: &str) -> bool {
    value
        .chars()
        .any(|character| character.is_whitespace() || character.is_ascii_control())
}

fn has_unambiguous_ip_host(origin: &str, url: &HttpUrl) -> bool {
    let Ok(normalized_address) = url.host().parse::<IpAddr>() else {
        return true;
    };
    original_origin_host(origin)
        .and_then(|host| host.parse::<IpAddr>().ok())
        .is_some_and(|address| address == normalized_address)
}

fn original_origin_host(origin: &str) -> Option<&str> {
    let (_, authority_and_path) = origin.split_once("://")?;
    let authority = authority_and_path
        .strip_suffix('/')
        .unwrap_or(authority_and_path);
    if let Some(bracketed) = authority.strip_prefix('[') {
        return bracketed.split_once(']').map(|(host, _)| host);
    }
    Some(
        authority
            .rsplit_once(':')
            .map_or(authority, |(host, _)| host),
    )
}

fn is_valid_domain(host: &str) -> bool {
    host.len() <= 253
        && host.split('.').all(|label| {
            !label.is_empty()
                && label.len() <= 63
                && label
                    .as_bytes()
                    .first()
                    .is_some_and(u8::is_ascii_alphanumeric)
                && label
                    .as_bytes()
                    .last()
                    .is_some_and(u8::is_ascii_alphanumeric)
                && label
                    .bytes()
                    .all(|character| character.is_ascii_alphanumeric() || character == b'-')
        })
}

fn domain_matches(host: &str, domain: &str) -> bool {
    host == domain
        || host
            .strip_suffix(domain)
            .is_some_and(|prefix| prefix.ends_with('.'))
}

#[cfg(test)]
mod tests;
