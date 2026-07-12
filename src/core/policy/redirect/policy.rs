use super::headers::RedirectHeaderPolicy;
use crate::core::policy::error::PolicyError;
use crate::core::policy::request::RequestBodyMutation;
use crate::core::url::HttpUrl;

const HTTPS_SCHEME: &str = "https";
const HTTP_SCHEME: &str = "http";

pub(super) struct RedirectSecurityPolicy {
    pub(super) block_error: Option<PolicyError>,
    pub(super) body: RequestBodyMutation,
    pub(super) header_policy: RedirectHeaderPolicy,
}

pub(super) fn redirect_security_policy(
    current_url: &HttpUrl,
    next_url: &HttpUrl,
    body: RequestBodyMutation,
) -> RedirectSecurityPolicy {
    let header_policy = if current_url.is_same_origin(next_url) {
        RedirectHeaderPolicy::SameOrigin
    } else {
        RedirectHeaderPolicy::CrossOrigin
    };
    let block_error = if is_https_to_http_redirect(current_url, next_url) {
        Some(PolicyError::HttpsToHttpRedirectBlocked)
    } else {
        None
    };
    let body = if body == RequestBodyMutation::Preserve
        && header_policy == RedirectHeaderPolicy::CrossOrigin
    {
        RequestBodyMutation::Drop
    } else {
        body
    };

    RedirectSecurityPolicy {
        block_error,
        body,
        header_policy,
    }
}

fn is_https_to_http_redirect(current_url: &HttpUrl, next_url: &HttpUrl) -> bool {
    current_url.scheme() == HTTPS_SCHEME && next_url.scheme() == HTTP_SCHEME
}
