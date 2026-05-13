use crate::core::headers::HeaderPairs;

const BODY_HEADERS: &[&str] = &[
    "content-encoding",
    "content-length",
    "content-type",
    "transfer-encoding",
];

const CROSS_ORIGIN_HEADERS: &[&str] = &[
    "authorization",
    "cookie",
    "origin",
    "proxy-authorization",
    "referer",
];

pub struct RedirectHeaderPolicy {
    pub preserve_body: bool,
    pub remove_sensitive_headers: bool,
}

pub fn redirect_headers(headers: HeaderPairs, policy: RedirectHeaderPolicy) -> HeaderPairs {
    headers
        .into_iter()
        .filter(|(name, _value)| {
            keep_redirect_header(name, policy.preserve_body, policy.remove_sensitive_headers)
        })
        .collect()
}

fn keep_redirect_header(name: &str, preserve_body: bool, remove_sensitive_headers: bool) -> bool {
    let name = name.to_ascii_lowercase();
    if !preserve_body && BODY_HEADERS.contains(&name.as_str()) {
        return false;
    }
    if remove_sensitive_headers && CROSS_ORIGIN_HEADERS.contains(&name.as_str()) {
        return false;
    }
    true
}
