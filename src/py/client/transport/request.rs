use super::client::TransportClients;
use super::context::RawResponseContext;
use super::errors::policy_error;
use crate::core::client::{
    with_connection_limit_timeout, with_request_write_timeout, ConnectionLimitContext,
    RequestWriteTimeoutContext,
};
use crate::core::headers::HeaderPairs;
use crate::core::numeric::duration_from_secs;
use crate::core::policy::{
    redirect_headers, PolicyMutation, PolicyPipeline, PolicyRequest, RequestBodyMutation,
    RequestBodyPolicy, ResponseHead, ResponsePolicyAction, RetryDecision, RetryPolicy,
    RetryStopReason, TransportRoute,
};
use crate::core::request::{build_request, RequestBodyParts, RequestParts};
use crate::core::response::BufferedBodyBudget;
use crate::core::url::HttpUrl;
use crate::errors::FogHttpError;
use crate::messages::REQUEST_TOTAL_TIMEOUT;
use crate::py::client::acquire::{AcquireGate, AcquirePermit};
use crate::py::client::policy_hooks::PythonPolicyHooks;
use crate::py::client::timeout_diagnostics::{
    remaining_duration, timeout_error, TimeoutContext, TimeoutPhase,
};
use crate::py::client::upload_body::RawUploadBody;
use crate::py::response::RawRequestInfo;
use crate::py::retry::{
    RawRetryAttempt, RawRetryTrace, RetryAttemptCompletion, RetryTraceOutcome, RetryTraceRecorder,
};
use hyper::body::Incoming;
use hyper::Response;
use hyper_util::client::legacy::Error as HyperClientError;
use pyo3::prelude::*;
use pyo3::types::PyAny;
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime};

pub struct TransportRequest {
    pub method: String,
    pub url: String,
    pub headers: HeaderPairs,
    pub body: Option<Vec<u8>>,
    pub body_stream: Option<Py<RawUploadBody>>,
    pub body_replayable: bool,
    pub use_proxy_transport: bool,
    pub proxy_policy: String,
    pub proxy_authorization: Option<String>,
    pub total_timeout: f64,
    pub read_timeout: f64,
    pub write_timeout: f64,
    pub max_response_body_size: Option<usize>,
    pub buffered_body_budget: BufferedBodyBudget,
    pub follow_redirects: bool,
    pub max_redirects: usize,
    pub retry_policy: Option<RetryPolicy>,
    pub policy_hooks: Option<Arc<PythonPolicyHooks>>,
    pub extensions: Option<Py<PyAny>>,
}

pub(super) struct RequestState {
    pub(super) method: String,
    pub(super) url: HttpUrl,
    pub(super) headers: HeaderPairs,
    pub(super) body: RequestBodyState,
    pub(super) body_policy: RequestBodyPolicy,
    policy: PolicyPipeline,
    policy_hooks: Option<Arc<PythonPolicyHooks>>,
    extensions: Option<Py<PyAny>>,
    pub(super) proxy_authorization: Option<String>,
    pub(super) total_timeout: f64,
    pub(super) read_timeout: f64,
    pub(super) write_timeout: Duration,
    pub(super) write_timeout_secs: f64,
    pub(super) max_response_body_size: Option<usize>,
    pub(super) buffered_body_budget: BufferedBodyBudget,
    retry_attempt: usize,
    completed_retries: usize,
    retry_trace: RetryTraceRecorder,
}

impl RequestState {
    pub(super) fn begin_transport_hop(&mut self) {
        self.retry_trace.begin_transport_hop();
    }

    pub(super) fn take_request_parts(&mut self, route: TransportRoute) -> PyResult<RequestParts> {
        Ok(RequestParts {
            method: self.method.clone(),
            url: self.url.as_str().to_owned(),
            headers: self.headers.clone(),
            body: self.body.take_body_parts()?,
            proxy_authorization: self.plain_http_proxy_authorization(route),
        })
    }

    fn plain_http_proxy_authorization(&self, route: TransportRoute) -> Option<String> {
        if route == TransportRoute::Proxy && self.url.scheme() == "http" {
            return self.proxy_authorization.clone();
        }
        None
    }

    pub(super) fn request_info(&self) -> RawRequestInfo {
        RawRequestInfo {
            method: self.method.clone(),
            url: self.url.as_str().to_owned(),
            headers: self.headers.clone(),
        }
    }

    pub(super) fn origin(&self) -> String {
        self.url.origin()
    }

    pub(super) fn has_request_body(&self) -> bool {
        self.body.has_request_body()
    }

    pub(super) fn write_timeout_context(
        &self,
        origin: &str,
        redirect_hop: usize,
    ) -> Option<RequestWriteTimeoutContext> {
        if !self.has_request_body() {
            return None;
        }
        Some(RequestWriteTimeoutContext::new(
            self.write_timeout,
            self.write_timeout_secs,
            origin.to_owned(),
            redirect_hop,
        ))
    }

    pub(super) fn connection_limit_context(
        origin: &str,
        redirect_hop: usize,
        pool_timeout: f64,
    ) -> PyResult<ConnectionLimitContext> {
        let timeout = duration_from_secs("Timeouts.pool", pool_timeout)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(ConnectionLimitContext::new(
            timeout,
            pool_timeout,
            origin.to_owned(),
            redirect_hop,
        ))
    }

    pub(super) fn response_context<'a>(
        &self,
        started: Instant,
        origin: &'a str,
        redirect_hop: usize,
    ) -> RawResponseContext<'a> {
        RawResponseContext {
            started,
            total_timeout: self.total_timeout,
            read_timeout: self.read_timeout,
            max_response_body_size: self.max_response_body_size,
            buffered_body_budget: self.buffered_body_budget.clone(),
            origin,
            redirect_hop,
        }
    }

    pub(super) fn transport_route(&self, redirect_hop: usize) -> PyResult<TransportRoute> {
        let request = self.policy_request();
        let route = self
            .policy
            .before_send(request)
            .map_err(|error| policy_error(&error))?;
        if let Some(hooks) = self.policy_hooks.as_ref() {
            hooks.before_send(request, redirect_hop, self.extensions.as_ref())?;
        }
        Ok(route)
    }

    pub(super) fn on_response_headers(
        &mut self,
        status_code: u16,
        headers: &HeaderPairs,
        redirect_hop: usize,
    ) -> PyResult<Option<PendingResponsePolicyAction>> {
        self.retry_trace.observe_response(status_code, redirect_hop);
        let request = self.policy_request();
        let response = ResponseHead::new(status_code, headers);
        let action = self.policy.on_response_headers(request, response);
        if let Some(hooks) = self.policy_hooks.as_ref() {
            hooks.on_response_headers(request, response, redirect_hop, self.extensions.as_ref())?;
        }
        Ok(action.map(|action| PendingResponsePolicyAction {
            action,
            response: self.response_body_snapshot(status_code, headers),
        }))
    }

    pub(super) fn retry_on_response(
        &self,
        status_code: u16,
        headers: &HeaderPairs,
    ) -> Option<PendingRetryDecision> {
        if !self.policy.retries_enabled() {
            return None;
        }
        let response = ResponseHead::new(status_code, headers);
        self.policy
            .on_retryable_response(
                self.policy_request(),
                response,
                self.completed_retries,
                fastrand::f64(),
                SystemTime::now(),
            )
            .map(|decision| PendingRetryDecision {
                decision,
                trigger: RetryTrigger::Status(status_code),
            })
    }

    pub(super) fn retry_on_network_error(&self) -> Option<PendingRetryDecision> {
        if !self.policy.retries_enabled() {
            return None;
        }
        self.policy
            .on_network_error(
                self.policy_request(),
                self.completed_retries,
                fastrand::f64(),
            )
            .map(|decision| PendingRetryDecision {
                decision,
                trigger: RetryTrigger::NetworkError,
            })
    }

    pub(super) fn commit_retry_decision(
        &mut self,
        pending: &PendingRetryDecision,
        decision_elapsed: Duration,
        redirect_hop: usize,
        completion: RetryAttemptCompletion,
    ) -> RetryAction {
        let action = pending.action();
        self.retry_trace.record(pending.raw_attempt(
            self.retry_attempt,
            &self.method,
            self.url.origin(),
            redirect_hop,
            decision_elapsed,
            completion,
        ));
        action
    }

    pub(super) fn advance_retry_attempt(&mut self) {
        self.completed_retries += 1;
        self.retry_attempt += 1;
    }

    pub(super) fn finish_retry_trace(
        &mut self,
        outcome: RetryTraceOutcome,
        status_code: Option<u16>,
        redirect_hop: usize,
        elapsed: Duration,
    ) -> Option<RawRetryTrace> {
        if !self.retry_trace.is_enabled() {
            return None;
        }
        let observed_response = self.retry_trace.observed_response();
        let terminal_attempt = RawRetryAttempt {
            attempt: self.retry_attempt,
            method: self.method.clone(),
            origin: self.url.origin(),
            redirect_hop: observed_response.map_or(redirect_hop, |response| response.redirect_hop),
            status_code: status_code
                .or_else(|| observed_response.map(|response| response.status_code)),
            error_type: None,
            decision: None,
            reason: None,
            backoff: 0.0,
            decision_elapsed: None,
            completed_elapsed: elapsed.as_secs_f64(),
            completion: RetryAttemptCompletion::Complete,
        };
        self.retry_trace.finish(
            terminal_attempt,
            outcome,
            status_code,
            elapsed.as_secs_f64(),
        )
    }

    pub(super) fn after_response_body(
        &mut self,
        pending: PendingResponsePolicyAction,
        completed_redirects: usize,
    ) -> PyResult<()> {
        let PendingResponsePolicyAction { action, response } = pending;
        let request = self.policy_request();
        let mutation = self
            .policy
            .after_response_body(request, action, completed_redirects)
            .map_err(|error| policy_error(&error))?;
        if let (Some(hooks), Some(response)) = (self.policy_hooks.as_ref(), response.as_ref()) {
            hooks.after_response_body(
                request,
                response.as_view(),
                completed_redirects,
                self.extensions.as_ref(),
            )?;
        }
        self.apply_policy_mutation(mutation);
        Ok(())
    }

    fn response_body_snapshot(
        &self,
        status_code: u16,
        headers: &HeaderPairs,
    ) -> Option<ResponseSnapshot> {
        self.policy_hooks
            .as_ref()
            .filter(|hooks| hooks.observes_response_body())
            .map(|_| ResponseSnapshot {
                headers: headers.clone(),
                status_code,
            })
    }

    fn policy_request(&self) -> PolicyRequest<'_> {
        PolicyRequest::new(&self.method, &self.url, self.body_policy)
    }

    fn apply_policy_mutation(&mut self, mutation: PolicyMutation) {
        let PolicyMutation::Redirect {
            body,
            header_policy,
            method,
            url,
        } = mutation;

        self.method = method.to_owned();
        self.url = url;
        self.headers = redirect_headers(std::mem::take(&mut self.headers), body, header_policy);

        if body == RequestBodyMutation::Drop {
            self.body = RequestBodyState::Empty;
            self.body_policy = RequestBodyPolicy::Empty;
        }
    }

    pub(super) fn try_from(parts: TransportRequest) -> PyResult<Self> {
        let url = HttpUrl::parse(&parts.url).map_err(FogHttpError::new_err)?;
        let write_timeout = duration_from_secs("Timeouts.write", parts.write_timeout)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let body = RequestBodyState::from_raw_parts(parts.body, parts.body_stream);
        let body_policy =
            RequestBodyPolicy::from_request(body.has_request_body(), parts.body_replayable);
        let retry_trace = if parts.retry_policy.is_some() {
            RetryTraceRecorder::enabled()
        } else {
            RetryTraceRecorder::disabled()
        };
        let policy = PolicyPipeline::new(
            &parts.proxy_policy,
            parts.use_proxy_transport,
            &url,
            parts.follow_redirects,
            parts.max_redirects,
            parts.retry_policy,
        )
        .map_err(|error| policy_error(&error))?;

        Ok(Self {
            method: parts.method.to_uppercase(),
            url,
            headers: parts.headers,
            body,
            body_policy,
            policy,
            policy_hooks: parts.policy_hooks,
            extensions: parts.extensions,
            proxy_authorization: parts.proxy_authorization,
            total_timeout: parts.total_timeout,
            read_timeout: parts.read_timeout,
            write_timeout,
            write_timeout_secs: parts.write_timeout,
            max_response_body_size: parts.max_response_body_size,
            buffered_body_budget: parts.buffered_body_budget,
            retry_attempt: 1,
            completed_retries: 0,
            retry_trace,
        })
    }
}

pub(super) async fn send_current_hop(
    clients: &TransportClients,
    state: &mut RequestState,
    origin: &str,
    redirect_hop: usize,
    pool_timeout: f64,
    started: Instant,
    route: TransportRoute,
) -> PyResult<Result<(Response<Incoming>, RawRequestInfo), HyperClientError>> {
    let request_info = state.request_info();
    let response_headers_timeout_context = TimeoutContext::new(
        TimeoutPhase::ResponseHeaders,
        started,
        state.total_timeout,
        origin,
        redirect_hop,
    );
    let write_timeout_context = state.write_timeout_context(origin, redirect_hop);
    let connection_limit_context =
        RequestState::connection_limit_context(origin, redirect_hop, pool_timeout)?;
    let request = build_request(state.take_request_parts(route)?)?;
    let use_write_timeout_transport = write_timeout_context.is_some();
    debug_assert_eq!(use_write_timeout_transport, state.has_request_body());
    let client = clients.select(route, use_write_timeout_transport)?;
    let response = tokio::time::timeout(
        remaining_duration("Timeouts.total", &response_headers_timeout_context)?,
        with_connection_limit_timeout(
            Some(connection_limit_context),
            with_request_write_timeout(write_timeout_context, client.request(request)),
        ),
    )
    .await
    .map_err(|_| timeout_error(&response_headers_timeout_context, REQUEST_TOTAL_TIMEOUT))?;

    Ok(response.map(|response| (response, request_info)))
}

pub(super) async fn acquire_request_slot(
    acquire_gate: &AcquireGate,
    origin: &str,
    pool_timeout: f64,
    started: Instant,
    total_timeout: f64,
    redirect_hop: usize,
) -> PyResult<AcquirePermit> {
    let context = TimeoutContext::new(
        TimeoutPhase::PoolAcquire,
        started,
        total_timeout,
        origin,
        redirect_hop,
    );
    tokio::time::timeout(
        remaining_duration("Timeouts.total", &context)?,
        acquire_gate.acquire(origin, pool_timeout, redirect_hop),
    )
    .await
    .map_err(|_| timeout_error(&context, REQUEST_TOTAL_TIMEOUT))?
}

pub(super) struct PendingRetryDecision {
    decision: RetryDecision,
    trigger: RetryTrigger,
}

impl PendingRetryDecision {
    pub(super) fn should_retry(&self) -> bool {
        matches!(self.decision, RetryDecision::Retry { .. })
    }

    fn action(&self) -> RetryAction {
        match self.decision {
            RetryDecision::Retry { delay } => RetryAction::Retry(delay),
            RetryDecision::Stop { .. } => RetryAction::Stop,
        }
    }

    fn raw_attempt(
        &self,
        attempt: usize,
        method: &str,
        origin: String,
        redirect_hop: usize,
        decision_elapsed: Duration,
        completion: RetryAttemptCompletion,
    ) -> RawRetryAttempt {
        let (decision, reason, backoff) = match self.decision {
            RetryDecision::Retry { delay } => ("retry", self.trigger.reason(), delay.as_secs_f64()),
            RetryDecision::Stop {
                reason: RetryStopReason::NonReplayableBody,
            } => ("block_non_replayable", "non_replayable_body", 0.0),
            RetryDecision::Stop {
                reason: RetryStopReason::MethodNotAllowed,
            } => ("stop", "method_not_allowed", 0.0),
            RetryDecision::Stop {
                reason: RetryStopReason::RetriesExhausted,
            } => ("stop", "retries_exhausted", 0.0),
        };
        let decision_elapsed = decision_elapsed.as_secs_f64();
        RawRetryAttempt {
            attempt,
            method: method.to_owned(),
            origin,
            redirect_hop,
            status_code: self.trigger.status_code(),
            error_type: self.trigger.error_type().map(str::to_owned),
            decision: Some(decision.to_owned()),
            reason: Some(reason.to_owned()),
            backoff,
            decision_elapsed: Some(decision_elapsed),
            completed_elapsed: decision_elapsed,
            completion,
        }
    }
}

#[derive(Clone, Copy)]
enum RetryTrigger {
    NetworkError,
    Status(u16),
}

impl RetryTrigger {
    fn status_code(self) -> Option<u16> {
        match self {
            Self::Status(status_code) => Some(status_code),
            Self::NetworkError => None,
        }
    }

    fn error_type(self) -> Option<&'static str> {
        matches!(self, Self::NetworkError).then_some("NetworkError")
    }

    fn reason(self) -> &'static str {
        match self {
            Self::Status(_) => "status",
            Self::NetworkError => "network_error",
        }
    }
}

#[derive(Clone, Copy)]
pub(super) enum RetryAction {
    Retry(Duration),
    Stop,
}

pub(super) struct PendingResponsePolicyAction {
    action: ResponsePolicyAction,
    response: Option<ResponseSnapshot>,
}

struct ResponseSnapshot {
    headers: HeaderPairs,
    status_code: u16,
}

impl ResponseSnapshot {
    fn as_view(&self) -> ResponseHead<'_> {
        ResponseHead::new(self.status_code, &self.headers)
    }
}

pub(super) enum RequestBodyState {
    Empty,
    Buffered(Vec<u8>),
    Streaming(Py<RawUploadBody>),
}

impl RequestBodyState {
    fn from_raw_parts(body: Option<Vec<u8>>, body_stream: Option<Py<RawUploadBody>>) -> Self {
        if let Some(body_stream) = body_stream {
            return Self::Streaming(body_stream);
        }

        match body {
            Some(content) if !content.is_empty() => Self::Buffered(content),
            _ => Self::Empty,
        }
    }

    fn has_request_body(&self) -> bool {
        !matches!(self, Self::Empty)
    }

    fn take_body_parts(&mut self) -> PyResult<RequestBodyParts> {
        match self {
            Self::Empty => Ok(RequestBodyParts::Buffered(None)),
            Self::Buffered(content) => Ok(RequestBodyParts::Buffered(Some(content.clone()))),
            Self::Streaming(body_stream) => {
                let (receiver, content_length) =
                    Python::attach(|py| body_stream.borrow(py).take_receiver(py))?;
                Ok(RequestBodyParts::Streaming {
                    receiver,
                    content_length,
                })
            }
        }
    }
}
