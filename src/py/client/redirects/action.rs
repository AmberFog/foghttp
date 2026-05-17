use super::method::redirect_method;
use super::policy::redirect_security_policy;
use super::status::redirect_status_code;
use super::utils::header_value;
use crate::core::url::HttpUrl;

pub enum RedirectDecision {
    Block(&'static str),
    Follow(RedirectAction),
}

pub struct RedirectAction {
    pub method: String,
    pub preserve_body: bool,
    pub remove_sensitive_headers: bool,
    pub url: String,
}

pub fn redirect_decision(
    method: &str,
    url: &str,
    status_code: u16,
    headers: &[(String, String)],
) -> Option<RedirectDecision> {
    let status_code = redirect_status_code(status_code)?;
    let location = header_value(headers, "location")?;
    let (next_method, preserve_body) = redirect_method(method, status_code)?;
    let current_url = HttpUrl::parse(url).ok()?;
    let next_url = current_url.join(location).ok()?;
    let policy = redirect_security_policy(&current_url, &next_url, next_method, preserve_body);

    if let Some(reason) = policy.block_reason {
        return Some(RedirectDecision::Block(reason));
    }

    Some(RedirectDecision::Follow(RedirectAction {
        method: next_method.to_owned(),
        preserve_body: policy.preserve_body,
        remove_sensitive_headers: policy.remove_sensitive_headers,
        url: next_url.as_str().to_owned(),
    }))
}
