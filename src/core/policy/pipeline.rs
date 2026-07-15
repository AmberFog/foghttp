use super::error::PolicyError;
use super::proxy::{ProxyPolicy, TransportRoute};
use super::redirect::{redirect_decision, RedirectAction, RedirectDecision, RedirectHeaderPolicy};
use super::request::{PolicyRequest, RequestBodyMutation, ResponseHead};
use super::retry::{RetryDecision, RetryPolicy};
use crate::core::url::HttpUrl;
use std::time::SystemTime;

#[derive(Debug)]
struct RedirectPolicy {
    max_redirects: usize,
}

#[derive(Debug)]
pub(crate) struct PolicyPipeline {
    proxy: ProxyPolicy,
    redirect: Option<RedirectPolicy>,
    retry: Option<RetryPolicy>,
}

pub(crate) struct ResponsePolicyAction {
    decision: RedirectDecision,
    max_redirects: usize,
}

pub(crate) enum PolicyMutation {
    Redirect {
        body: RequestBodyMutation,
        header_policy: RedirectHeaderPolicy,
        method: &'static str,
        url: HttpUrl,
    },
}

impl PolicyPipeline {
    pub(crate) fn retries_enabled(&self) -> bool {
        self.retry.is_some()
    }

    pub(crate) fn new(
        proxy_policy: &str,
        initial_use_proxy_transport: bool,
        initial_url: &HttpUrl,
        follow_redirects: bool,
        max_redirects: usize,
        retry: Option<RetryPolicy>,
    ) -> Result<Self, PolicyError> {
        let initial_route = if initial_use_proxy_transport {
            TransportRoute::Proxy
        } else {
            TransportRoute::Direct
        };
        let proxy = ProxyPolicy::parse(proxy_policy, initial_route, initial_url)?;
        let redirect = follow_redirects.then_some(RedirectPolicy { max_redirects });
        Ok(Self {
            proxy,
            redirect,
            retry,
        })
    }

    pub(crate) fn on_retryable_response(
        &self,
        request: PolicyRequest<'_>,
        response: ResponseHead<'_>,
        completed_retries: usize,
        jitter_sample: f64,
        now: SystemTime,
    ) -> Option<RetryDecision> {
        self.retry
            .as_ref()?
            .on_response(request, response, completed_retries, jitter_sample, now)
    }

    pub(crate) fn on_network_error(
        &self,
        request: PolicyRequest<'_>,
        completed_retries: usize,
        jitter_sample: f64,
    ) -> Option<RetryDecision> {
        self.retry
            .as_ref()?
            .on_network_error(request, completed_retries, jitter_sample)
    }

    pub(crate) fn before_send(
        &self,
        request: PolicyRequest<'_>,
    ) -> Result<TransportRoute, PolicyError> {
        self.proxy.route(request.url())
    }

    pub(crate) fn on_response_headers(
        &self,
        request: PolicyRequest<'_>,
        response: ResponseHead<'_>,
    ) -> Option<ResponsePolicyAction> {
        let redirect = self.redirect.as_ref()?;
        redirect_decision(request, response).map(|decision| ResponsePolicyAction {
            decision,
            max_redirects: redirect.max_redirects,
        })
    }

    pub(crate) fn after_response_body(
        &self,
        request: PolicyRequest<'_>,
        action: ResponsePolicyAction,
        completed_redirects: usize,
    ) -> Result<PolicyMutation, PolicyError> {
        if completed_redirects >= action.max_redirects {
            return Err(PolicyError::RedirectLimitExceeded {
                max_redirects: action.max_redirects,
                origin: request.url().origin(),
            });
        }
        self.redirect_mutation(request, action.decision)
    }

    fn redirect_mutation(
        &self,
        request: PolicyRequest<'_>,
        decision: RedirectDecision,
    ) -> Result<PolicyMutation, PolicyError> {
        let action = match decision {
            RedirectDecision::Block(error) => return Err(error),
            RedirectDecision::Follow(action) => action,
        };

        if action.body == RequestBodyMutation::Preserve && !request.body().can_replay() {
            return Err(PolicyError::NonReplayableRequestBodyRedirect);
        }
        self.proxy.validate_redirect(&action.url)?;
        Ok(redirect_mutation(action))
    }
}

fn redirect_mutation(action: RedirectAction) -> PolicyMutation {
    PolicyMutation::Redirect {
        body: action.body,
        header_policy: action.header_policy,
        method: action.method,
        url: action.url,
    }
}
