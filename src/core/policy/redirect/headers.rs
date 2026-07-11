use crate::core::headers::HeaderPairs;
use crate::core::policy::request::RequestBodyMutation;

const BODY_HEADERS: &[&str] = &[
    "content-encoding",
    "content-length",
    "content-type",
    "transfer-encoding",
];

const CROSS_ORIGIN_HEADERS: &[&str] = &[
    "authorization",
    "cookie",
    "host",
    "origin",
    "proxy-authorization",
    "referer",
];

pub(crate) fn redirect_headers(
    headers: HeaderPairs,
    body: RequestBodyMutation,
    remove_sensitive_headers: bool,
) -> HeaderPairs {
    headers
        .into_iter()
        .filter(|(name, _value)| keep_redirect_header(name, body, remove_sensitive_headers))
        .collect()
}

fn keep_redirect_header(
    name: &str,
    body: RequestBodyMutation,
    remove_sensitive_headers: bool,
) -> bool {
    let name = name.to_ascii_lowercase();
    if body == RequestBodyMutation::Drop && BODY_HEADERS.contains(&name.as_str()) {
        return false;
    }
    if remove_sensitive_headers && CROSS_ORIGIN_HEADERS.contains(&name.as_str()) {
        return false;
    }
    true
}
