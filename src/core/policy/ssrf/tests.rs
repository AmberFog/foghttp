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
fn allocated_ipv6_unicast_ranges_match_iana_2025_10_10_snapshot() {
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
    let policy = SsrfPolicy::new(vec!["https".to_owned()], vec![], vec![]).expect("valid policy");

    let error = policy
        .validate_url(&url("http://8.8.8.8/path"))
        .expect_err("HTTP must be blocked by an HTTPS-only policy");

    assert_eq!(error.reason, SsrfViolationReason::SchemeNotAllowed);
}

#[test]
fn violation_reason_codes_are_stable() {
    let cases = [
        (
            SsrfViolationReason::DestinationNotAllowed,
            "destination_not_allowed",
        ),
        (SsrfViolationReason::NonPublicAddress, "non_public_address"),
        (
            SsrfViolationReason::ProxyResolutionUnsupported,
            "proxy_resolution_unsupported",
        ),
        (SsrfViolationReason::SchemeNotAllowed, "scheme_not_allowed"),
    ];

    for (reason, expected) in cases {
        assert_eq!(reason.as_code(), expected);
    }
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
