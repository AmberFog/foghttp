use super::*;
use crate::core::headers::response_headers;
use hyper::header::{HeaderMap, SET_COOKIE};

const NOW_SECONDS: i64 = 1_752_000_000;

fn now() -> OffsetDateTime {
    OffsetDateTime::from_unix_timestamp(NOW_SECONDS).expect("test timestamp")
}

fn url(value: &str) -> HttpUrl {
    HttpUrl::parse(value).expect("test URL")
}

fn set_cookie(value: impl Into<String>) -> HeaderPairs {
    vec![(SET_COOKIE_HEADER_NAME.to_owned(), value.into())]
}

fn raw_set_cookie(value: &[u8]) -> HeaderPairs {
    let mut headers = HeaderMap::new();
    headers.append(
        SET_COOKIE,
        HeaderValue::from_bytes(value).expect("valid raw Set-Cookie value"),
    );
    response_headers(&headers)
}

#[test]
fn selects_cookies_by_domain_and_path_in_protocol_order() {
    let jar = CookieJar::new();
    let origin = url("https://api.example.test/login");
    jar.store_response_at(
        &origin,
        &[
            ("set-cookie".to_owned(), "host=1; Path=/".to_owned()),
            (
                "set-cookie".to_owned(),
                "scoped=2; Domain=example.test; Path=/private".to_owned(),
            ),
        ],
        now(),
    );

    assert_eq!(
        jar.request_header_at(&url("https://api.example.test/private/item"), now()),
        Some("scoped=2; host=1".to_owned()),
    );
    assert_eq!(
        jar.request_header_at(&url("https://www.example.test/private/item"), now()),
        Some("scoped=2".to_owned()),
    );
    assert_eq!(
        jar.request_header_at(&url("https://api.example.test/public"), now()),
        Some("host=1".to_owned()),
    );
    assert_eq!(
        jar.request_header_at(&url("https://unrelated.test/private/item"), now()),
        None,
    );
}

#[test]
fn preserves_opaque_cookie_values_without_percent_decoding() {
    let jar = CookieJar::new();
    let origin = url("https://example.test/");
    jar.store_response_at(
        &origin,
        &[
            (
                "set-cookie".to_owned(),
                "opaque=%41%2F%25; Path=/".to_owned(),
            ),
            (
                "set-cookie".to_owned(),
                "quoted=\"a%2Fb\"; Path=/".to_owned(),
            ),
        ],
        now(),
    );

    assert_eq!(
        jar.request_header_at(&origin, now()),
        Some("opaque=%41%2F%25; quoted=\"a%2Fb\"".to_owned()),
    );
}

#[test]
fn serializes_nameless_cookies_without_an_equals_sign() {
    let jar = CookieJar::new();
    let origin = url("https://example.test/");

    jar.store_response_at(&origin, &set_cookie("nameless-token; Path=/"), now());
    jar.store_response_at(&origin, &set_cookie("named=value; Path=/"), now());
    assert_eq!(
        jar.request_header_at(&origin, now()),
        Some("nameless-token; named=value".to_owned()),
    );

    jar.store_response_at(&origin, &set_cookie("=replacement-token; Path=/"), now());
    assert_eq!(
        jar.request_header_at(&origin, now()),
        Some("replacement-token; named=value".to_owned()),
    );
}

#[test]
fn rejects_reserved_prefixes_in_nameless_cookie_values() {
    let jar = CookieJar::new();
    let origin = url("https://example.test/");

    jar.store_response_at(&origin, &set_cookie("safe-token; Path=/"), now());
    jar.store_response_at(
        &origin,
        &set_cookie("__Secure-hidden; Secure; Path=/"),
        now(),
    );
    jar.store_response_at(
        &origin,
        &set_cookie("=__Host-hidden; Secure; Path=/"),
        now(),
    );
    assert_eq!(
        jar.request_header_at(&origin, now()),
        Some("safe-token".to_owned()),
    );
}

#[test]
fn rejects_non_ascii_domain_attributes_but_accepts_ascii_punycode() {
    let jar = CookieJar::new();
    let origin = url("https://xn--mnchen-3ya.de/");

    jar.store_response_at(
        &origin,
        &set_cookie("unicode=one; Domain=münchen.de; Path=/"),
        now(),
    );
    assert_eq!(jar.request_header_at(&origin, now()), None);

    jar.store_response_at(
        &origin,
        &set_cookie("punycode=two; Domain=xn--mnchen-3ya.de; Path=/"),
        now(),
    );
    assert_eq!(
        jar.request_header_at(&origin, now()),
        Some("punycode=two".to_owned()),
    );
}

#[test]
fn counts_attribute_limits_in_original_response_header_octets() {
    let jar = CookieJar::new();
    let secure_origin = url("https://example.test/");
    let plain_origin = url("http://example.test/");

    let mut exact_secure = b"exact=value; Secure=".to_vec();
    exact_secure.extend(std::iter::repeat_n(0x80, MAX_COOKIE_ATTRIBUTE_VALUE_OCTETS));
    jar.store_response_at(&secure_origin, &raw_set_cookie(&exact_secure), now());

    let mut oversized_secure = b"oversized=value; Secure=".to_vec();
    oversized_secure.extend(std::iter::repeat_n(
        0x80,
        MAX_COOKIE_ATTRIBUTE_VALUE_OCTETS + 1,
    ));
    jar.store_response_at(&secure_origin, &raw_set_cookie(&oversized_secure), now());

    let mut non_ascii_domain = b"domain=value; Domain=".to_vec();
    non_ascii_domain.extend(std::iter::repeat_n(0x80, 600));
    jar.store_response_at(&secure_origin, &raw_set_cookie(&non_ascii_domain), now());

    assert_eq!(
        jar.request_header_at(&secure_origin, now()),
        Some("exact=value; oversized=value".to_owned()),
    );
    assert_eq!(
        jar.request_header_at(&plain_origin, now()),
        Some("oversized=value".to_owned()),
    );
}

#[test]
fn empty_domain_after_leading_dot_uses_host_only_scope() {
    let jar = CookieJar::new();
    let origin = url("https://example.test/");
    jar.store_response_at(&origin, &set_cookie("dot=one; Domain=.; Path=/"), now());

    assert_eq!(
        jar.request_header_at(&origin, now()),
        Some("dot=one".to_owned()),
    );
    assert_eq!(
        jar.request_header_at(&url("https://sub.example.test/"), now()),
        None,
    );
}

#[test]
fn host_only_flag_is_part_of_identity_and_deletion() {
    let jar = CookieJar::new();
    let origin = url("https://example.test/");
    jar.store_response_at(&origin, &set_cookie("id=host; Path=/"), now());
    jar.store_response_at(
        &origin,
        &set_cookie("id=domain; Domain=example.test; Path=/"),
        now(),
    );
    assert_eq!(
        jar.request_header_at(&origin, now()),
        Some("id=host; id=domain".to_owned()),
    );

    jar.store_response_at(
        &origin,
        &set_cookie("id=; Domain=example.test; Path=/; Max-Age=0"),
        now(),
    );
    assert_eq!(
        jar.request_header_at(&origin, now()),
        Some("id=host".to_owned()),
    );

    jar.store_response_at(
        &origin,
        &set_cookie("id=domain-two; Domain=example.test; Path=/"),
        now(),
    );
    jar.store_response_at(&origin, &set_cookie("id=; Path=/; Max-Age=0"), now());
    assert_eq!(
        jar.request_header_at(&origin, now()),
        Some("id=domain-two".to_owned()),
    );
}

#[test]
fn host_only_cookies_match_ipv4_and_ipv6_literals_exactly() {
    let jar = CookieJar::new();
    let ipv4 = url("http://127.0.0.1/");
    let ipv6 = url("http://[::1]/");
    jar.store_response_at(&ipv4, &set_cookie("ipv4=one; Secure; Path=/"), now());
    jar.store_response_at(&ipv6, &set_cookie("ipv6=two; Secure; Path=/"), now());

    assert_eq!(
        jar.request_header_at(&ipv4, now()),
        Some("ipv4=one".to_owned()),
    );
    assert_eq!(
        jar.request_header_at(&ipv6, now()),
        Some("ipv6=two".to_owned()),
    );
    assert_eq!(
        jar.request_header_at(&url("http://127.0.0.2/"), now()),
        None,
    );
}

#[test]
fn expires_and_deletes_cookies() {
    let jar = CookieJar::new();
    let origin = url("https://example.test/");
    jar.store_response_at(&origin, &set_cookie("short=1; Max-Age=1"), now());
    assert_eq!(
        jar.request_header_at(&origin, now()),
        Some("short=1".to_owned()),
    );
    assert_eq!(
        jar.request_header_at(&origin, now() + Duration::seconds(2)),
        None,
    );

    jar.store_response_at(&origin, &set_cookie("session=1; Path=/"), now());
    jar.store_response_at(&origin, &set_cookie("session=; Path=/; Max-Age=0"), now());
    assert_eq!(jar.request_header_at(&origin, now()), None);
}

#[test]
fn parses_cookie_dates_caps_lifetimes_and_honors_max_age_precedence() {
    let jar = CookieJar::new();
    let origin = url("https://example.test/");
    jar.store_response_at(
        &origin,
        &set_cookie("dated=one; Expires=18:40:01 2025 Jul 08"),
        now(),
    );
    assert_eq!(
        jar.request_header_at(&origin, now()),
        Some("dated=one".to_owned()),
    );
    assert_eq!(
        jar.request_header_at(&origin, now() + Duration::seconds(2)),
        None,
    );

    let far_future = vec![
        (
            "set-cookie".to_owned(),
            "max=one; Max-Age=999999999999999999999999999".to_owned(),
        ),
        (
            "set-cookie".to_owned(),
            "expires=two; Expires=Fri, 31 Dec 9999 23:59:59 GMT".to_owned(),
        ),
        (
            "set-cookie".to_owned(),
            "precedence=three; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=10".to_owned(),
        ),
    ];
    jar.store_response_at(&origin, &far_future, now());
    assert_eq!(
        jar.request_header_at(&origin, now() + Duration::seconds(9)),
        Some("max=one; expires=two; precedence=three".to_owned()),
    );
    assert_eq!(
        jar.request_header_at(&origin, now() + Duration::seconds(11)),
        Some("max=one; expires=two".to_owned()),
    );
    assert_eq!(
        jar.request_header_at(
            &origin,
            now() + Duration::seconds(MAX_COOKIE_AGE_SECONDS - 1),
        ),
        Some("max=one; expires=two".to_owned()),
    );
    assert_eq!(
        jar.request_header_at(&origin, now() + Duration::seconds(MAX_COOKIE_AGE_SECONDS)),
        None,
    );
}

#[test]
fn ignores_oversized_attributes_without_replacing_earlier_valid_values() {
    let jar = CookieJar::new();
    let origin = url("https://example.test/root");
    let oversized_max_age = "9".repeat(MAX_COOKIE_ATTRIBUTE_VALUE_OCTETS + 1);
    jar.store_response_at(
        &origin,
        &set_cookie(format!("short=one; Max-Age=1; Max-Age={oversized_max_age}")),
        now(),
    );
    assert_eq!(
        jar.request_header_at(&origin, now() + Duration::seconds(2)),
        None,
    );

    let oversized_path = format!("/{}", "x".repeat(MAX_COOKIE_ATTRIBUTE_VALUE_OCTETS));
    jar.store_response_at(
        &origin,
        &set_cookie(format!("scoped=two; Path=/private; Path={oversized_path}")),
        now(),
    );
    assert_eq!(jar.request_header_at(&origin, now()), None);
    assert_eq!(
        jar.request_header_at(&url("https://example.test/private"), now()),
        Some("scoped=two".to_owned()),
    );
}

#[test]
fn ignores_malformed_oversized_and_insecure_secure_cookies_independently() {
    let jar = CookieJar::new();
    let origin = url("http://example.test/");
    let oversized = format!("large={}", "x".repeat(MAX_COOKIE_PAIR_OCTETS));
    jar.store_response_at(
        &origin,
        &[
            ("set-cookie".to_owned(), "=; Path=/".to_owned()),
            ("set-cookie".to_owned(), oversized),
            (
                "set-cookie".to_owned(),
                "injected=one\r\nCookie: two".to_owned(),
            ),
            ("set-cookie".to_owned(), "secure=secret; Secure".to_owned()),
            ("set-cookie".to_owned(), "valid=1".to_owned()),
        ],
        now(),
    );

    assert_eq!(
        jar.request_header_at(&origin, now()),
        Some("valid=1".to_owned()),
    );
}

#[test]
fn enforces_cookie_pair_size_at_the_exact_boundary() {
    let jar = CookieJar::new();
    let origin = url("https://example.test/");
    let accepted = format!(
        "limit={}",
        "x".repeat(MAX_COOKIE_PAIR_OCTETS - "limit".len())
    );
    let rejected = format!(
        "oversized={}",
        "x".repeat(MAX_COOKIE_PAIR_OCTETS + 1 - "oversized".len())
    );
    jar.store_response_at(&origin, &set_cookie(accepted), now());
    jar.store_response_at(&origin, &set_cookie(rejected), now());

    let header = jar
        .request_header_at(&origin, now())
        .expect("the boundary-sized cookie is stored");
    assert!(header.starts_with("limit="));
    assert!(!header.contains("oversized="));
}

#[test]
fn replacement_preserves_creation_order() {
    let jar = CookieJar::new();
    let origin = url("https://example.test/");
    jar.store_response_at(&origin, &set_cookie("first=one; Path=/"), now());
    jar.store_response_at(&origin, &set_cookie("second=two; Path=/"), now());
    jar.store_response_at(&origin, &set_cookie("first=updated; Path=/"), now());

    assert_eq!(
        jar.request_header_at(&origin, now()),
        Some("first=updated; second=two".to_owned()),
    );
}

#[test]
fn enforces_secure_cookie_prefixes() {
    let jar = CookieJar::new();
    let origin = url("https://example.test/");
    jar.store_response_at(
        &origin,
        &[
            (
                "set-cookie".to_owned(),
                "__secure-missing=one; Path=/".to_owned(),
            ),
            (
                "set-cookie".to_owned(),
                "__Host-domain=two; Secure; Domain=example.test; Path=/".to_owned(),
            ),
            (
                "set-cookie".to_owned(),
                "__HOST-missing-path=two; Secure".to_owned(),
            ),
            (
                "set-cookie".to_owned(),
                "__Host-valid=three; Secure; Path=/".to_owned(),
            ),
        ],
        now(),
    );

    assert_eq!(
        jar.request_header_at(&origin, now()),
        Some("__Host-valid=three".to_owned()),
    );
}

#[test]
fn host_prefix_uses_present_normalized_path_attribute() {
    let jar = CookieJar::new();
    let root_default = url("https://example.test/set");
    jar.store_response_at(
        &root_default,
        &[
            (
                "set-cookie".to_owned(),
                "__Host-relative=one; Secure; Path=relative".to_owned(),
            ),
            (
                "set-cookie".to_owned(),
                "__Host-empty=two; Secure; Path=".to_owned(),
            ),
            (
                "set-cookie".to_owned(),
                "__Host-bare=three; Secure; Path".to_owned(),
            ),
        ],
        now(),
    );

    let nested_default = url("https://example.test/private/set");
    jar.store_response_at(
        &nested_default,
        &set_cookie("__Host-nested=four; Secure; Path=relative"),
        now(),
    );

    assert_eq!(
        jar.request_header_at(&root_default, now()),
        Some("__Host-relative=one; __Host-empty=two; __Host-bare=three".to_owned()),
    );
    assert_eq!(
        jar.request_header_at(&url("https://example.test/private/resource"), now()),
        Some("__Host-relative=one; __Host-empty=two; __Host-bare=three".to_owned()),
    );
}

#[test]
fn evicts_non_secure_cookies_before_secure_cookies_for_a_domain() {
    let jar = CookieJar::new();
    let origin = url("https://example.test/");
    jar.store_response_at(
        &origin,
        &set_cookie("session=secret; Secure; Path=/"),
        now(),
    );
    for index in 0..MAX_COOKIES_PER_DOMAIN {
        jar.store_response_at(&origin, &set_cookie(format!("cookie{index}=value")), now());
    }
    let header = jar
        .request_header_at(&origin, now())
        .expect("capacity leaves stored cookies");
    let pairs = header.split("; ").collect::<Vec<_>>();
    assert_eq!(pairs.len(), MAX_COOKIES_PER_DOMAIN);
    assert!(pairs.contains(&"session=secret"));
    assert!(!pairs.contains(&"cookie0=value"));
    assert!(pairs.contains(&"cookie49=value"));

    let oversized_attribute = format!("small=value; Path=/{}", "x".repeat(MAX_SET_COOKIE_OCTETS));
    jar.store_response_at(&origin, &set_cookie(oversized_attribute), now());
    assert!(!jar
        .request_header_at(&origin, now())
        .expect("existing cookies remain")
        .contains("small=value"));
}

#[test]
fn recent_access_protects_a_cookie_from_domain_eviction() {
    let jar = CookieJar::new();
    let origin = url("https://example.test/");
    jar.store_response_at(&origin, &set_cookie("keep=one; Path=/keep"), now());
    jar.store_response_at(&origin, &set_cookie("evict=two; Path=/other"), now());
    for index in 0..(MAX_COOKIES_PER_DOMAIN - 2) {
        jar.store_response_at(
            &origin,
            &set_cookie(format!("filler{index}=value; Path=/other")),
            now(),
        );
    }

    assert_eq!(
        jar.request_header_at(&url("https://example.test/keep"), now()),
        Some("keep=one".to_owned()),
    );
    jar.store_response_at(&origin, &set_cookie("new=three; Path=/other"), now());

    let other = jar
        .request_header_at(&url("https://example.test/other"), now())
        .expect("matching cookies remain");
    assert!(!other.contains("evict=two"));
    assert!(other.contains("new=three"));
    assert_eq!(
        jar.request_header_at(&url("https://example.test/keep"), now()),
        Some("keep=one".to_owned()),
    );
}

#[test]
fn bounds_total_cookie_count() {
    let jar = CookieJar::new();
    for index in 0..MAX_COOKIES {
        let origin = url(&format!("https://host{index}.example.test/"));
        jar.store_response_at(&origin, &set_cookie(format!("cookie{index}=value")), now());
    }
    assert_eq!(
        jar.request_header_at(&url("https://host0.example.test/"), now()),
        Some("cookie0=value".to_owned()),
    );
    let newest = url(&format!("https://host{MAX_COOKIES}.example.test/"));
    jar.store_response_at(
        &newest,
        &set_cookie(format!("cookie{MAX_COOKIES}=value")),
        now(),
    );

    assert_eq!(
        jar.request_header_at(&url("https://host1.example.test/"), now()),
        None,
    );
    assert_eq!(
        jar.request_header_at(&newest, now()),
        Some(format!("cookie{MAX_COOKIES}=value")),
    );
}

#[test]
fn insecure_origin_cannot_overlay_existing_secure_cookie() {
    let jar = CookieJar::new();
    let secure_origin = url("https://example.test/login");
    let insecure_origin = url("http://example.test/login/en");
    jar.store_response_at(
        &secure_origin,
        &set_cookie("session=secure; Secure; Path=/login"),
        now(),
    );

    jar.store_response_at(
        &insecure_origin,
        &set_cookie("session=attacker; Path=/login/en"),
        now(),
    );
    jar.store_response_at(
        &insecure_origin,
        &set_cookie("session=; Path=/login; Max-Age=0"),
        now(),
    );
    assert_eq!(
        jar.request_header_at(&url("https://example.test/login/en"), now()),
        Some("session=secure".to_owned()),
    );

    jar.store_response_at(
        &insecure_origin,
        &set_cookie("session=allowed; Path=/"),
        now(),
    );
    assert_eq!(
        jar.request_header_at(&url("https://example.test/login/en"), now()),
        Some("session=secure; session=allowed".to_owned()),
    );
}
