mod cookies;
mod error;
mod pipeline;
mod proxy;
mod redirect;
mod request;
mod retry;
mod ssrf;

pub(crate) use cookies::CookieJar;
pub(crate) use error::PolicyError;
pub(crate) use pipeline::{PolicyMutation, PolicyPipeline, ResponsePolicyAction};
pub(crate) use proxy::TransportRoute;
pub(crate) use redirect::{redirect_headers, RedirectHeaderPolicy};
pub(crate) use request::{PolicyRequest, RequestBodyMutation, RequestBodyPolicy, ResponseHead};
pub(crate) use retry::{RetryDecision, RetryPolicy, RetryStopReason};
pub(crate) use ssrf::{validate_resolved_address, SsrfPolicy, SsrfViolation};

#[cfg(test)]
mod tests;
