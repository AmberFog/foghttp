use crate::core::headers::HeaderPairs;
use crate::core::url::HttpUrl;
use cookie::time::{OffsetDateTime, SignedDuration};
use cookie::Cookie as RawCookie;
use hyper::header::HeaderValue;
use rfc_6265::date::parse_cookie_date;
use rfc_6265::domain::{domain_matches, to_ascii};
use rfc_6265::path::{default_path, path_matches};
use std::net::IpAddr;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

const MAX_COOKIE_PAIR_OCTETS: usize = 4096;
const MAX_COOKIE_ATTRIBUTE_VALUE_OCTETS: usize = 1024;
const MAX_SET_COOKIE_OCTETS: usize = 16 * 1024;
const MAX_COOKIES_PER_DOMAIN: usize = 50;
const MAX_COOKIES: usize = 3000;
const MAX_COOKIE_AGE_SECONDS: i64 = 400 * 24 * 60 * 60;
const SET_COOKIE_HEADER_NAME: &str = "set-cookie";
const SECURE_COOKIE_PREFIX: &str = "__Secure-";
const HOST_COOKIE_PREFIX: &str = "__Host-";

#[derive(Clone)]
pub(crate) struct CookieJar {
    store: Arc<Mutex<CookieStore>>,
}

impl CookieJar {
    pub(crate) fn new() -> Self {
        Self {
            store: Arc::new(Mutex::new(CookieStore::default())),
        }
    }

    pub(crate) fn request_header(&self, url: &HttpUrl) -> Option<String> {
        self.request_header_at(url, OffsetDateTime::now_utc())
    }

    pub(crate) fn store_response(&self, url: &HttpUrl, headers: &HeaderPairs) {
        self.store_response_at(url, headers, OffsetDateTime::now_utc());
    }

    fn request_header_at(&self, url: &HttpUrl, now: OffsetDateTime) -> Option<String> {
        let host = canonical_cookie_domain(&url.host())?;
        let secure = is_trustworthy_origin(url);
        let mut store = self.lock();
        store.purge_expired(now);
        store.request_header(&host, url.path(), secure)
    }

    fn store_response_at(&self, url: &HttpUrl, headers: &[(String, String)], now: OffsetDateTime) {
        let Some(host) = canonical_cookie_domain(&url.host()) else {
            return;
        };
        let secure = is_trustworthy_origin(url);
        let mut store = self.lock();
        store.purge_expired(now);

        for (name, value) in headers {
            if name.eq_ignore_ascii_case(SET_COOKIE_HEADER_NAME)
                && value.len() <= MAX_SET_COOKIE_OCTETS
            {
                store.store(value, &host, url.path(), secure, now);
            }
        }
    }

    fn lock(&self) -> MutexGuard<'_, CookieStore> {
        self.store.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

// RFC 10025 includes host_only and last_access in storage semantics. Keep one
// storage owner while delegating opaque parsing and date/domain/path algorithms.
#[derive(Default)]
struct CookieStore {
    cookies: Vec<StoredCookie>,
    next_creation: u64,
    next_access: u64,
}

impl CookieStore {
    fn store(
        &mut self,
        value: &str,
        origin_host: &str,
        request_path: &str,
        origin_secure: bool,
        now: OffsetDateTime,
    ) {
        let Some(mut candidate) =
            StoredCookie::parse(value, origin_host, request_path, origin_secure, now)
        else {
            return;
        };

        if !origin_secure && self.would_overlay_secure_cookie(&candidate) {
            return;
        }

        let existing = self
            .cookies
            .iter()
            .position(|cookie| cookie.has_same_identity(&candidate));
        if candidate.is_expired(now) {
            if let Some(index) = existing {
                self.cookies.remove(index);
            }
            return;
        }

        candidate.last_access = self.next_access;
        self.next_access = self.next_access.saturating_add(1);
        if let Some(index) = existing {
            candidate.creation = self.cookies[index].creation;
            self.cookies[index] = candidate;
            return;
        }

        candidate.creation = self.next_creation;
        let domain = candidate.domain.clone();
        self.next_creation = self.next_creation.saturating_add(1);
        self.cookies.push(candidate);
        self.enforce_capacity(&domain);
    }

    fn request_header(&mut self, host: &str, path: &str, secure: bool) -> Option<String> {
        let mut matching = self
            .cookies
            .iter()
            .enumerate()
            .filter_map(|(index, cookie)| cookie.matches(host, path, secure).then_some(index))
            .collect::<Vec<_>>();
        matching.sort_by(|left, right| {
            self.cookies[*right]
                .path
                .len()
                .cmp(&self.cookies[*left].path.len())
                .then_with(|| {
                    self.cookies[*left]
                        .creation
                        .cmp(&self.cookies[*right].creation)
                })
        });

        if matching.is_empty() {
            return None;
        }
        let access = self.next_access;
        self.next_access = self.next_access.saturating_add(1);
        let mut header = String::new();
        for index in matching {
            let cookie = &mut self.cookies[index];
            cookie.last_access = access;
            if !header.is_empty() {
                header.push_str("; ");
            }
            header.push_str(&cookie.name);
            header.push('=');
            header.push_str(&cookie.value);
        }
        Some(header)
    }

    fn purge_expired(&mut self, now: OffsetDateTime) {
        self.cookies.retain(|cookie| !cookie.is_expired(now));
    }

    fn would_overlay_secure_cookie(&self, candidate: &StoredCookie) -> bool {
        self.cookies.iter().any(|existing| {
            existing.secure
                && existing.name == candidate.name
                && (domain_matches(&candidate.domain, &existing.domain)
                    || domain_matches(&existing.domain, &candidate.domain))
                && path_matches(&candidate.path, &existing.path)
        })
    }

    fn enforce_capacity(&mut self, domain: &str) {
        while self
            .cookies
            .iter()
            .filter(|cookie| cookie.domain == domain)
            .count()
            > MAX_COOKIES_PER_DOMAIN
        {
            let has_non_secure = self
                .cookies
                .iter()
                .any(|cookie| cookie.domain == domain && !cookie.secure);
            let index = self
                .cookies
                .iter()
                .enumerate()
                .filter(|(_index, cookie)| {
                    cookie.domain == domain && (!has_non_secure || !cookie.secure)
                })
                .min_by_key(|(_index, cookie)| (cookie.last_access, cookie.creation))
                .map(|(index, _cookie)| index)
                .expect("an over-capacity domain has a cookie");
            self.cookies.remove(index);
        }

        while self.cookies.len() > MAX_COOKIES {
            let index = self
                .cookies
                .iter()
                .enumerate()
                .min_by_key(|(_index, cookie)| (cookie.last_access, cookie.creation))
                .map(|(index, _cookie)| index)
                .expect("an over-capacity store has a cookie");
            self.cookies.remove(index);
        }
    }
}

struct StoredCookie {
    name: String,
    value: String,
    domain: String,
    path: String,
    host_only: bool,
    secure: bool,
    expires_at: Option<OffsetDateTime>,
    creation: u64,
    last_access: u64,
}

impl StoredCookie {
    fn parse(
        value: &str,
        origin_host: &str,
        request_path: &str,
        origin_secure: bool,
        now: OffsetDateTime,
    ) -> Option<Self> {
        if contains_disallowed_control(value) {
            return None;
        }
        let parsed = RawCookie::parse(value.to_owned()).ok()?;
        let name = parsed.name();
        let cookie_value = parsed.value();
        if !is_safe_cookie_pair(name, cookie_value) {
            return None;
        }

        let attributes = CookieAttributes::parse(value, now);
        let (domain, host_only) = match attributes.domain {
            Some(domain) if !domain.is_empty() => {
                let domain = canonical_cookie_domain(domain.strip_prefix('.').unwrap_or(domain))?;
                if !domain_matches(origin_host, &domain) {
                    return None;
                }
                (domain, false)
            }
            _ => (origin_host.to_owned(), true),
        };
        let explicit_root_path = attributes.path == Some("/");
        let path = attributes
            .path
            .filter(|path| path.starts_with('/'))
            .unwrap_or_else(|| default_path(request_path))
            .to_owned();
        let secure = attributes.secure;
        if secure && !origin_secure {
            return None;
        }
        if has_ascii_case_insensitive_prefix(name, SECURE_COOKIE_PREFIX) && !secure {
            return None;
        }
        if has_ascii_case_insensitive_prefix(name, HOST_COOKIE_PREFIX)
            && (!secure || !host_only || !explicit_root_path)
        {
            return None;
        }

        Some(Self {
            name: name.to_owned(),
            value: cookie_value.to_owned(),
            domain,
            path,
            host_only,
            secure,
            expires_at: attributes.max_age.or(attributes.expires),
            creation: 0,
            last_access: 0,
        })
    }

    fn has_same_identity(&self, other: &Self) -> bool {
        self.name == other.name
            && self.domain == other.domain
            && self.host_only == other.host_only
            && self.path == other.path
    }

    fn is_expired(&self, now: OffsetDateTime) -> bool {
        self.expires_at.is_some_and(|expires_at| expires_at <= now)
    }

    fn matches(&self, host: &str, path: &str, secure: bool) -> bool {
        (if self.host_only {
            self.domain == host
        } else {
            domain_matches(host, &self.domain)
        }) && path_matches(path, &self.path)
            && (!self.secure || secure)
    }
}

#[derive(Default)]
struct CookieAttributes<'a> {
    domain: Option<&'a str>,
    path: Option<&'a str>,
    secure: bool,
    expires: Option<OffsetDateTime>,
    max_age: Option<OffsetDateTime>,
}

impl<'a> CookieAttributes<'a> {
    fn parse(value: &'a str, now: OffsetDateTime) -> Self {
        let mut attributes = Self::default();
        for raw_attribute in value.split(';').skip(1) {
            let (name, attribute_value) =
                raw_attribute.split_once('=').unwrap_or((raw_attribute, ""));
            let name = trim_cookie_whitespace(name);
            let attribute_value = trim_cookie_whitespace(attribute_value);
            if attribute_value.len() > MAX_COOKIE_ATTRIBUTE_VALUE_OCTETS {
                continue;
            }

            if name.eq_ignore_ascii_case("domain") {
                attributes.domain = Some(attribute_value);
            } else if name.eq_ignore_ascii_case("path") {
                attributes.path = Some(attribute_value);
            } else if name.eq_ignore_ascii_case("secure") {
                attributes.secure = true;
            } else if name.eq_ignore_ascii_case("expires") {
                if let Some(expires) = parse_cookie_date(attribute_value) {
                    attributes.expires = Some(clamp_cookie_expiry(expires, now));
                }
            } else if name.eq_ignore_ascii_case("max-age") {
                if let Some(expires) = parse_max_age(attribute_value, now) {
                    attributes.max_age = Some(expires);
                }
            }
        }
        attributes
    }
}

fn parse_max_age(value: &str, now: OffsetDateTime) -> Option<OffsetDateTime> {
    let (negative, digits) = match value.strip_prefix('-') {
        Some(digits) => (true, digits),
        None => (false, value),
    };
    if digits.is_empty() || !digits.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    if negative || digits.bytes().all(|byte| byte == b'0') {
        return Some(now);
    }

    let seconds = digits.bytes().fold(0_i64, |seconds, byte| {
        seconds
            .saturating_mul(10)
            .saturating_add(i64::from(byte - b'0'))
            .min(MAX_COOKIE_AGE_SECONDS)
    });
    Some(now.saturating_add(SignedDuration::seconds(seconds)))
}

fn clamp_cookie_expiry(expires: OffsetDateTime, now: OffsetDateTime) -> OffsetDateTime {
    expires.min(now.saturating_add(SignedDuration::seconds(MAX_COOKIE_AGE_SECONDS)))
}

fn trim_cookie_whitespace(value: &str) -> &str {
    value.trim_matches([' ', '\t'])
}

fn contains_disallowed_control(value: &str) -> bool {
    value
        .bytes()
        .any(|byte| matches!(byte, 0x00..=0x08 | 0x0a..=0x1f | 0x7f))
}

fn is_safe_cookie_pair(name: &str, value: &str) -> bool {
    name.len() + value.len() <= MAX_COOKIE_PAIR_OCTETS
        && name.is_ascii()
        && value.is_ascii()
        && HeaderValue::from_str(&format!("{name}={value}")).is_ok()
}

fn has_ascii_case_insensitive_prefix(value: &str, prefix: &str) -> bool {
    value
        .as_bytes()
        .get(..prefix.len())
        .is_some_and(|candidate| candidate.eq_ignore_ascii_case(prefix.as_bytes()))
}

fn canonical_cookie_domain(value: &str) -> Option<String> {
    value
        .parse::<IpAddr>()
        .map(|address| address.to_string())
        .ok()
        .or_else(|| to_ascii(value))
}

fn is_trustworthy_origin(url: &HttpUrl) -> bool {
    if url.scheme() == "https" {
        return true;
    }
    let host = url.host();
    if let Ok(address) = host.parse::<IpAddr>() {
        return address.is_loopback();
    }
    host.eq_ignore_ascii_case("localhost") || host.to_ascii_lowercase().ends_with(".localhost")
}

#[cfg(test)]
mod tests {
    use super::*;

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
            jar.request_header_at(&origin, now() + SignedDuration::seconds(2)),
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
            jar.request_header_at(&origin, now() + SignedDuration::seconds(2)),
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
            jar.request_header_at(&origin, now() + SignedDuration::seconds(9)),
            Some("max=one; expires=two; precedence=three".to_owned()),
        );
        assert_eq!(
            jar.request_header_at(&origin, now() + SignedDuration::seconds(11)),
            Some("max=one; expires=two".to_owned()),
        );
        assert_eq!(
            jar.request_header_at(
                &origin,
                now() + SignedDuration::seconds(MAX_COOKIE_AGE_SECONDS - 1),
            ),
            Some("max=one; expires=two".to_owned()),
        );
        assert_eq!(
            jar.request_header_at(
                &origin,
                now() + SignedDuration::seconds(MAX_COOKIE_AGE_SECONDS),
            ),
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
            jar.request_header_at(&origin, now() + SignedDuration::seconds(2)),
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
                ("set-cookie".to_owned(), "missing-pair".to_owned()),
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

        let oversized_attribute =
            format!("small=value; Path=/{}", "x".repeat(MAX_SET_COOKIE_OCTETS));
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
}
