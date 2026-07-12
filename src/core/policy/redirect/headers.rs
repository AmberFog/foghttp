use crate::core::headers::HeaderPairs;
use crate::core::policy::request::RequestBodyMutation;

const ALWAYS_REBUILT_HEADERS: &[&str] = &[
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "proxy-authorization",
    "proxy-connection",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
];

const CONDITIONAL_HEADERS: &[&str] = &[
    "if-match",
    "if-modified-since",
    "if-none-match",
    "if-range",
    "if-unmodified-since",
];

const CONTENT_HEADER_PREFIX: &str = "content-";
const REPRESENTATION_HEADERS: &[&str] = &["digest", "last-modified", "repr-digest"];

const CROSS_ORIGIN_HEADERS: &[&str] = &["authorization", "cookie", "origin", "referer"];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RedirectHeaderPolicy {
    SameOrigin,
    CrossOrigin,
}

pub(crate) fn redirect_headers(
    headers: HeaderPairs,
    body: RequestBodyMutation,
    policy: RedirectHeaderPolicy,
) -> HeaderPairs {
    let connection_options = connection_options(&headers);
    headers
        .into_iter()
        .filter(|(name, _value)| keep_redirect_header(name, body, policy, &connection_options))
        .collect()
}

fn keep_redirect_header(
    name: &str,
    body: RequestBodyMutation,
    policy: RedirectHeaderPolicy,
    connection_options: &[String],
) -> bool {
    if header_in(name, ALWAYS_REBUILT_HEADERS)
        || header_in(name, CONDITIONAL_HEADERS)
        || connection_options
            .iter()
            .any(|option| name.eq_ignore_ascii_case(option))
    {
        return false;
    }
    if body == RequestBodyMutation::Drop && is_content_metadata_header(name) {
        return false;
    }
    policy != RedirectHeaderPolicy::CrossOrigin || !header_in(name, CROSS_ORIGIN_HEADERS)
}

fn header_in(name: &str, headers: &[&str]) -> bool {
    headers
        .iter()
        .any(|candidate| name.eq_ignore_ascii_case(candidate))
}

fn is_content_metadata_header(name: &str) -> bool {
    name.get(..CONTENT_HEADER_PREFIX.len())
        .is_some_and(|prefix| prefix.eq_ignore_ascii_case(CONTENT_HEADER_PREFIX))
        || header_in(name, REPRESENTATION_HEADERS)
}

fn connection_options(headers: &HeaderPairs) -> Vec<String> {
    headers
        .iter()
        .filter(|(name, _value)| name.eq_ignore_ascii_case("connection"))
        .flat_map(|(_name, value)| value.split(','))
        .map(str::trim)
        .filter(|name| !name.is_empty())
        .map(str::to_owned)
        .collect()
}
