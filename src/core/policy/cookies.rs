use crate::core::headers::HeaderPairs;
use crate::core::url::HttpUrl;
use hyper::header::HeaderValue;
use rfc_6265::date::parse_cookie_date;
use rfc_6265::domain::{domain_matches, to_ascii};
use rfc_6265::grammar::{has_host_prefix, has_secure_prefix};
use rfc_6265::path::{default_path, path_matches};
use std::net::IpAddr;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use time::{Duration, OffsetDateTime};

const MAX_COOKIE_PAIR_OCTETS: usize = 4096;
const MAX_COOKIE_ATTRIBUTE_VALUE_OCTETS: usize = 1024;
const MAX_SET_COOKIE_OCTETS: usize = 16 * 1024;
const MAX_COOKIES_PER_DOMAIN: usize = 50;
const MAX_COOKIES: usize = 3000;
const MAX_COOKIE_AGE_SECONDS: i64 = 400 * 24 * 60 * 60;
const SET_COOKIE_HEADER_NAME: &str = "set-cookie";

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
                && response_header_octet_len(value)
                    .is_some_and(|octets| octets <= MAX_SET_COOKIE_OCTETS)
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
// storage owner while reusing the crate's date, domain, path, and prefix primitives.
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
            header.push_str(&cookie.wire_pair);
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
    wire_pair: String,
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
        let (name, cookie_value) = parse_cookie_pair(value)?;
        let wire_pair = serialize_cookie_pair(name, cookie_value)?;

        let attributes = CookieAttributes::parse(value, now);
        let domain_attribute = attributes
            .domain
            .map(|domain| domain.strip_prefix('.').unwrap_or(domain));
        let (domain, host_only) = match domain_attribute {
            Some(domain) if !domain.is_empty() => {
                if !domain.is_ascii() {
                    return None;
                }
                let domain = canonical_cookie_domain(domain)?;
                if !domain_matches(origin_host, &domain) {
                    return None;
                }
                (domain, false)
            }
            _ => (origin_host.to_owned(), true),
        };
        let path_attribute_present = attributes.path.is_some();
        let path = attributes
            .path
            .filter(|path| path.starts_with('/'))
            .unwrap_or_else(|| default_path(request_path))
            .to_owned();
        let secure = attributes.secure;
        if secure && !origin_secure {
            return None;
        }
        if has_secure_prefix(name) && !secure {
            return None;
        }
        if has_host_prefix(name)
            && (!secure || !host_only || !path_attribute_present || path != "/")
        {
            return None;
        }
        if name.is_empty() && (has_secure_prefix(cookie_value) || has_host_prefix(cookie_value)) {
            return None;
        }

        Some(Self {
            name: name.to_owned(),
            wire_pair,
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
            if response_header_octet_len(attribute_value)
                .is_none_or(|octets| octets > MAX_COOKIE_ATTRIBUTE_VALUE_OCTETS)
            {
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
    Some(now.saturating_add(Duration::seconds(seconds)))
}

fn clamp_cookie_expiry(expires: OffsetDateTime, now: OffsetDateTime) -> OffsetDateTime {
    expires.min(now.saturating_add(Duration::seconds(MAX_COOKIE_AGE_SECONDS)))
}

fn trim_cookie_whitespace(value: &str) -> &str {
    value.trim_matches([' ', '\t'])
}

fn contains_disallowed_control(value: &str) -> bool {
    value
        .bytes()
        .any(|byte| matches!(byte, 0x00..=0x08 | 0x0a..=0x1f | 0x7f))
}

// Response headers map each wire byte to one Latin-1 scalar. Counting UTF-8
// storage bytes would make obs-text consume two octets and change RFC limits.
fn response_header_octet_len(value: &str) -> Option<usize> {
    let mut octets = 0;
    for character in value.chars() {
        if character > '\u{ff}' {
            return None;
        }
        octets += 1;
    }
    Some(octets)
}

fn parse_cookie_pair(value: &str) -> Option<(&str, &str)> {
    let pair = value
        .split_once(';')
        .map_or(value, |(pair, _attributes)| pair);
    let (name, cookie_value) = pair.split_once('=').unwrap_or(("", pair));
    let name = trim_cookie_whitespace(name);
    let cookie_value = trim_cookie_whitespace(cookie_value);
    (!name.is_empty() || !cookie_value.is_empty()).then_some((name, cookie_value))
}

fn serialize_cookie_pair(name: &str, value: &str) -> Option<String> {
    if name.len() + value.len() > MAX_COOKIE_PAIR_OCTETS || !name.is_ascii() || !value.is_ascii() {
        return None;
    }
    let mut pair = String::with_capacity(name.len() + value.len() + usize::from(!name.is_empty()));
    if !name.is_empty() {
        pair.push_str(name);
        pair.push('=');
    }
    pair.push_str(value);
    HeaderValue::from_str(&pair).ok()?;
    Some(pair)
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
mod tests;
