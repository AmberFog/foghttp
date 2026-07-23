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

// Keep this conservative allowlist aligned with the IANA IPv6 Global Unicast registry.
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
mod tests {
    use super::{blocked_ip_kind, BlockedIpKind, SsrfPolicy, SsrfViolationReason};
    use crate::core::url::HttpUrl;
    use std::net::IpAddr;

    #[test]
    fn classifies_blocked_address_families_and_embedded_ipv4() {
        let cases = [
            ("127.0.0.1", BlockedIpKind::Loopback),
            ("10.0.0.1", BlockedIpKind::Private),
            ("169.254.10.20", BlockedIpKind::LinkLocal),
            ("169.254.169.254", BlockedIpKind::Metadata),
            ("224.0.0.1", BlockedIpKind::Multicast),
            ("100.100.100.200", BlockedIpKind::Metadata),
            ("192.88.99.1", BlockedIpKind::SpecialUse),
            ("::1", BlockedIpKind::Loopback),
            ("fd00::1", BlockedIpKind::Private),
            ("fe80::1", BlockedIpKind::LinkLocal),
            ("ff02::1", BlockedIpKind::Multicast),
            ("fd00:ec2::254", BlockedIpKind::Metadata),
            ("::ffff:127.0.0.1", BlockedIpKind::Loopback),
            ("::7f00:1", BlockedIpKind::Loopback),
            ("64:ff9b::7f00:1", BlockedIpKind::Loopback),
            ("64:ff9b:1::1", BlockedIpKind::SpecialUse),
            ("100:0:0:1::1", BlockedIpKind::SpecialUse),
            ("2001::1", BlockedIpKind::SpecialUse),
            ("2001:5::1", BlockedIpKind::SpecialUse),
            ("4000::1", BlockedIpKind::SpecialUse),
            ("2d00::1", BlockedIpKind::SpecialUse),
            ("3ffe::1", BlockedIpKind::SpecialUse),
            ("2002::1", BlockedIpKind::SpecialUse),
            ("5f00::1", BlockedIpKind::SpecialUse),
        ];

        for (address, expected) in cases {
            assert_eq!(
                blocked_ip_kind(address.parse::<IpAddr>().expect("valid address")),
                Some(expected),
                "unexpected classification for {address}"
            );
        }
        assert_eq!(
            blocked_ip_kind("8.8.8.8".parse().expect("valid address")),
            None
        );
        assert_eq!(
            blocked_ip_kind("192.0.0.9".parse().expect("valid address")),
            None
        );
        assert_eq!(
            blocked_ip_kind("192.0.0.10".parse().expect("valid address")),
            None
        );
        assert_eq!(
            blocked_ip_kind("2606:4700:4700::1111".parse().expect("valid address")),
            None
        );
        assert_eq!(
            blocked_ip_kind("64:ff9b::808:808".parse().expect("valid address")),
            None
        );
        for address in [
            "2001:1::1",
            "2001:1::2",
            "2001:1::3",
            "2001:3::1",
            "2001:4:112::1",
            "2001:20::1",
            "2001:30::1",
        ] {
            assert_eq!(
                blocked_ip_kind(address.parse().expect("valid address")),
                None,
                "globally reachable IANA assignment must pass: {address}"
            );
        }
    }

    #[test]
    fn allocated_ipv6_unicast_ranges_are_allowlisted_explicitly() {
        let allowed = [
            "2001:200::1",
            "2001:1200::1",
            "2001:1400::1",
            "2001:1800::1",
            "2001:2000::1",
            "2001:4000::1",
            "2001:4800::1",
            "2001:4c00::1",
            "2001:5000::1",
            "2001:8000::1",
            "2003::1",
            "2400::1",
            "2410::1",
            "2600::1",
            "2610::1",
            "2620::1",
            "2630::1",
            "2800::1",
            "2a00::1",
            "2a10::1",
            "2c00::1",
        ];
        for address in allowed {
            assert_eq!(
                blocked_ip_kind(address.parse().expect("valid address")),
                None,
                "allocated global-unicast address must pass: {address}"
            );
        }

        let reserved = [
            "2001:1000::1",
            "2001:4e00::1",
            "2001:6000::1",
            "2001:c000::1",
            "2003:4000::1",
            "2420::1",
            "2610:200::1",
            "2620:200::1",
        ];
        for address in reserved {
            assert_eq!(
                blocked_ip_kind(address.parse().expect("valid address")),
                Some(BlockedIpKind::SpecialUse),
                "IANA-reserved address must be blocked: {address}"
            );
        }
    }

    #[test]
    fn destination_allowlist_matches_exact_origins_and_domain_boundaries() {
        let policy = policy(vec!["https://api.example.com"], vec!["service.example"]);

        assert!(policy
            .validate_url(&url("https://api.example.com/path"))
            .is_ok());
        assert!(policy
            .validate_url(&url("https://service.example/path"))
            .is_ok());
        assert!(policy
            .validate_url(&url("http://child.service.example/path"))
            .is_ok());
        let error = policy
            .validate_url(&url("https://notservice.example/path"))
            .expect_err("domain boundary must not match");
        assert_eq!(error.reason, SsrfViolationReason::DestinationNotAllowed);
    }

    #[test]
    fn scheme_allowlist_is_enforced_before_network_access() {
        let policy =
            SsrfPolicy::new(vec!["https".to_owned()], vec![], vec![]).expect("valid policy");

        let error = policy
            .validate_url(&url("http://8.8.8.8/path"))
            .expect_err("HTTP must be blocked by an HTTPS-only policy");

        assert_eq!(error.reason, SsrfViolationReason::SchemeNotAllowed);
    }

    #[test]
    fn exact_ip_origin_can_explicitly_trust_a_private_service() {
        let policy = policy(vec!["http://127.0.0.1:8000"], vec![]);

        assert!(policy
            .validate_url(&url("http://127.0.0.1:8000/health"))
            .is_ok());
        assert!(policy
            .validate_url(&url("http://127.0.0.1:8001/health"))
            .is_err());
    }

    #[test]
    fn noncanonical_ip_origin_forms_are_rejected() {
        for origin in [
            "http://2130706433",
            "http://0x7f000001",
            "http://0177.0.0.1",
            "http://127.1",
            "http://0x7f.1",
        ] {
            assert!(
                SsrfPolicy::new(vec!["http".to_owned()], vec![origin.to_owned()], vec![]).is_err(),
                "ambiguous IP origin must be rejected: {origin}"
            );
        }
    }

    #[test]
    fn exact_origin_does_not_override_metadata_protection() {
        let policy = policy(vec!["http://169.254.169.254"], vec![]);

        assert!(policy
            .validate_url(&url("http://169.254.169.254/latest/meta-data"))
            .is_err());
    }

    #[test]
    fn resolved_hostnames_never_bypass_address_validation() {
        assert!(super::validate_resolved_address(
            "api.example.com",
            "127.0.0.1".parse().expect("valid")
        )
        .is_err());
    }

    fn policy(origins: Vec<&str>, domains: Vec<&str>) -> SsrfPolicy {
        SsrfPolicy::new(
            vec!["http".to_owned(), "https".to_owned()],
            origins.into_iter().map(str::to_owned).collect(),
            domains.into_iter().map(str::to_owned).collect(),
        )
        .expect("valid policy")
    }

    fn url(value: &str) -> HttpUrl {
        HttpUrl::parse(value).expect("valid URL")
    }
}
