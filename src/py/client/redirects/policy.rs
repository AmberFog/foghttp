use crate::core::method::{GET, HEAD};
use crate::core::url::HttpUrl;
use crate::messages::HTTPS_TO_HTTP_REDIRECT_BLOCKED;

const HTTPS_SCHEME: &str = "https";
const HTTP_SCHEME: &str = "http";

pub struct RedirectSecurityPolicy {
    pub block_reason: Option<&'static str>,
    pub preserve_body: bool,
    pub remove_sensitive_headers: bool,
}

pub fn redirect_security_policy(
    current_url: &HttpUrl,
    next_url: &HttpUrl,
    method: &str,
    preserve_body: bool,
) -> RedirectSecurityPolicy {
    let remove_sensitive_headers = !current_url.is_same_origin(next_url);
    let block_reason = if is_https_to_http_redirect(current_url, next_url) {
        Some(HTTPS_TO_HTTP_REDIRECT_BLOCKED)
    } else {
        None
    };
    let preserve_body =
        preserve_body && !(remove_sensitive_headers && can_replay_request_body(method));

    RedirectSecurityPolicy {
        block_reason,
        preserve_body,
        remove_sensitive_headers,
    }
}

fn is_https_to_http_redirect(current_url: &HttpUrl, next_url: &HttpUrl) -> bool {
    current_url.scheme() == HTTPS_SCHEME && next_url.scheme() == HTTP_SCHEME
}

fn can_replay_request_body(method: &str) -> bool {
    method != GET && method != HEAD
}
