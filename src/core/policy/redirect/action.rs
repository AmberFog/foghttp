use super::headers::RedirectHeaderPolicy;
use super::method::redirect_method;
use super::policy::redirect_security_policy;
use super::status::redirect_status_code;
use super::utils::header_value;
use crate::core::policy::error::PolicyError;
use crate::core::policy::request::{PolicyRequest, RequestBodyMutation, ResponseHead};
use crate::core::url::HttpUrl;

pub(in crate::core::policy) enum RedirectDecision {
    Block(PolicyError),
    Follow(RedirectAction),
}

pub(in crate::core::policy) struct RedirectAction {
    pub(in crate::core::policy) body: RequestBodyMutation,
    pub(in crate::core::policy) header_policy: RedirectHeaderPolicy,
    pub(in crate::core::policy) method: &'static str,
    pub(in crate::core::policy) url: HttpUrl,
}

pub(in crate::core::policy) fn redirect_decision(
    request: PolicyRequest<'_>,
    response: ResponseHead<'_>,
) -> Option<RedirectDecision> {
    let status_code = redirect_status_code(response.status_code())?;
    let location = header_value(response.headers(), "location")?;
    let (next_method, body) = redirect_method(request.method(), status_code)?;
    let next_url = request.url().join(location).ok()?;
    let policy = redirect_security_policy(request.url(), &next_url, body);

    if let Some(error) = policy.block_error {
        return Some(RedirectDecision::Block(error));
    }

    Some(RedirectDecision::Follow(RedirectAction {
        body: policy.body,
        header_policy: policy.header_policy,
        method: next_method,
        url: next_url,
    }))
}
