use crate::core::method::{GET, HEAD};
use crate::core::policy::error::PolicyError;
use crate::core::policy::request::RequestBodyMutation;
use crate::core::url::HttpUrl;

const HTTPS_SCHEME: &str = "https";
const HTTP_SCHEME: &str = "http";

pub(super) struct RedirectSecurityPolicy {
    pub(super) block_error: Option<PolicyError>,
    pub(super) body: RequestBodyMutation,
    pub(super) remove_sensitive_headers: bool,
}

pub(super) fn redirect_security_policy(
    current_url: &HttpUrl,
    next_url: &HttpUrl,
    method: &str,
    body: RequestBodyMutation,
) -> RedirectSecurityPolicy {
    let remove_sensitive_headers = !current_url.is_same_origin(next_url);
    let block_error = if is_https_to_http_redirect(current_url, next_url) {
        Some(PolicyError::HttpsToHttpRedirectBlocked)
    } else {
        None
    };
    let body = if body == RequestBodyMutation::Preserve
        && remove_sensitive_headers
        && can_replay_request_body(method)
    {
        RequestBodyMutation::Drop
    } else {
        body
    };

    RedirectSecurityPolicy {
        block_error,
        body,
        remove_sensitive_headers,
    }
}

fn is_https_to_http_redirect(current_url: &HttpUrl, next_url: &HttpUrl) -> bool {
    current_url.scheme() == HTTPS_SCHEME && next_url.scheme() == HTTP_SCHEME
}

fn can_replay_request_body(method: &str) -> bool {
    method != GET && method != HEAD
}
