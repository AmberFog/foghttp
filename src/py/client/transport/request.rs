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
    redirect_headers, CookieJar, PolicyMutation, PolicyPipeline, PolicyRequest,
    RedirectHeaderPolicy, RequestBodyMutation, RequestBodyPolicy, ResponseHead,
    ResponsePolicyAction, RetryDecision, RetryPolicy, RetryStopReason, SsrfPolicy, TransportRoute,
};
use crate::core::request::{build_request, RequestBodyParts, RequestParts};
use crate::core::response::BufferedBodyBudget;
use crate::core::url::HttpUrl;
use crate::errors::FogHttpError;
use crate::messages::REQUEST_TOTAL_TIMEOUT;
use crate::py::client::acquire::{AcquireGate, AcquirePermit};
use crate::py::client::auth::PythonAuth;
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
use std::collections::HashSet;
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime};

const COOKIE_HEADER_NAME: &str = "cookie";
const COOKIE_HEADER_WIRE_NAME: &str = "Cookie";

pub struct TransportRequest {
    pub method: String,
    pub url: String,
    pub headers: HeaderPairs,
    pub auth_override_headers: Option<Vec<String>>,
    pub auth_removed_headers: Vec<String>,
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
    pub ssrf_policy: Option<Arc<SsrfPolicy>>,
    pub cookie_jar: Option<CookieJar>,
    pub auth: Option<Arc<PythonAuth>>,
    pub policy_hooks: Option<Arc<PythonPolicyHooks>>,
    pub extensions: Option<Py<PyAny>>,
}

struct RequestCookieState {
    jar: CookieJar,
    managed_header: bool,
}

impl RequestCookieState {
    fn new(jar: CookieJar) -> Self {
        Self {
            jar,
            managed_header: false,
        }
    }

    fn attach(&mut self, url: &HttpUrl, headers: &mut HeaderPairs) {
        if headers
            .iter()
            .any(|(name, _value)| name.eq_ignore_ascii_case(COOKIE_HEADER_NAME))
        {
            return;
        }
        let Some(value) = self.jar.request_header(url) else {
            return;
        };
        headers.push((COOKIE_HEADER_WIRE_NAME.to_owned(), value));
        self.managed_header = true;
    }

    fn store_response(&self, url: &HttpUrl, headers: &HeaderPairs) {
        self.jar.store_response(url, headers);
    }

    fn remove_managed_header(&mut self, headers: &mut HeaderPairs) {
        if !self.managed_header {
            return;
        }
        headers.retain(|(name, _value)| !name.eq_ignore_ascii_case(COOKIE_HEADER_NAME));
        self.managed_header = false;
    }
}

struct RequestAuthState {
    provider: Arc<PythonAuth>,
    base_headers: HeaderPairs,
    active_headers: HashSet<String>,
    sensitive_headers: HashSet<String>,
    caller_owned_headers: HashSet<String>,
    caller_removed_headers: HashSet<String>,
}

impl RequestAuthState {
    fn new(
        provider: Arc<PythonAuth>,
        base_headers: HeaderPairs,
        override_headers: Option<Vec<String>>,
        removed_headers: Vec<String>,
    ) -> Self {
        let caller_owned_headers = match override_headers {
            Some(names) => normalized_header_names(names),
            None => base_headers
                .iter()
                .map(|(name, _value)| name.to_ascii_lowercase())
                .collect(),
        };
        Self {
            provider,
            base_headers,
            active_headers: HashSet::new(),
            sensitive_headers: HashSet::new(),
            caller_owned_headers,
            caller_removed_headers: normalized_header_names(removed_headers),
        }
    }

    fn can_apply_header(&self, name: &str, base_header_names: &HashSet<String>) -> bool {
        !(self.caller_removed_headers.contains(name)
            || self.caller_owned_headers.contains(name) && base_header_names.contains(name))
    }

    fn apply(
        &mut self,
        method: &str,
        url: &str,
        headers: &mut HeaderPairs,
        redirect_hop: usize,
        extensions: Option<&Py<PyAny>>,
    ) -> PyResult<()> {
        if !self.active_headers.is_empty() {
            headers.clone_from(&self.base_headers);
            self.active_headers.clear();
        }
        let base_header_names = headers
            .iter()
            .map(|(name, _value)| name.to_ascii_lowercase())
            .collect::<HashSet<_>>();
        let updates =
            self.provider
                .header_updates(method, url, headers, redirect_hop, extensions)?;
        let mut applied_names = HashSet::new();
        let mut applied_updates = Vec::with_capacity(updates.len());
        for (name, value) in updates {
            let normalized_name = name.to_ascii_lowercase();
            if self.can_apply_header(&normalized_name, &base_header_names) {
                applied_names.insert(normalized_name);
                applied_updates.push((name, value));
            }
        }
        headers.retain(|(name, _value)| !applied_names.contains(&name.to_ascii_lowercase()));
        headers.extend(applied_updates);
        self.sensitive_headers.extend(applied_names.iter().cloned());
        self.active_headers = applied_names;
        Ok(())
    }

    fn on_redirect(
        &mut self,
        body: RequestBodyMutation,
        header_policy: RedirectHeaderPolicy,
    ) -> HeaderPairs {
        let cross_origin = header_policy == RedirectHeaderPolicy::CrossOrigin;
        self.active_headers.clear();
        let mut headers =
            redirect_headers(std::mem::take(&mut self.base_headers), body, header_policy);
        if cross_origin {
            headers.retain(|(name, _value)| {
                !self.sensitive_headers.contains(&name.to_ascii_lowercase())
            });
        } else {
            self.base_headers.clone_from(&headers);
        }
        headers
    }

    fn sensitive_headers(&self) -> Vec<String> {
        let mut headers = self.sensitive_headers.iter().cloned().collect::<Vec<_>>();
        headers.sort_unstable();
        headers
    }
}

pub(super) struct RequestState {
    pub(super) method: String,
    pub(super) url: HttpUrl,
    pub(super) headers: HeaderPairs,
    pub(super) body: RequestBodyState,
    pub(super) body_policy: RequestBodyPolicy,
    policy: PolicyPipeline,
    cookies: Option<RequestCookieState>,
    auth: Option<RequestAuthState>,
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
        let sensitive_headers = self
            .auth
            .as_ref()
            .map_or_else(Vec::new, RequestAuthState::sensitive_headers);
        RawRequestInfo {
            method: self.method.clone(),
            url: self.url.as_str().to_owned(),
            headers: self.headers.clone(),
            sensitive_headers,
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

    pub(super) async fn transport_route(
        &mut self,
        redirect_hop: usize,
    ) -> PyResult<TransportRoute> {
        if let Some(cookies) = self.cookies.as_mut() {
            cookies.remove_managed_header(&mut self.headers);
        }
        let request = self.policy_request();
        let route = self
            .policy
            .before_send(request)
            .map_err(|error| policy_error(&error))?;
        if let Some(auth) = self.auth.as_mut() {
            let hook_ran = auth.provider.uses_hook();
            auth.apply(
                &self.method,
                self.url.as_str(),
                &mut self.headers,
                redirect_hop,
                self.extensions.as_ref(),
            )?;
            if hook_ran {
                // Let task aborts take effect before policy hooks or transport acquisition.
                tokio::task::yield_now().await;
            }
        }
        if let Some(cookies) = self.cookies.as_mut() {
            cookies.attach(&self.url, &mut self.headers);
        }
        let request = self.policy_request();
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
        if let Some(cookies) = self.cookies.as_ref() {
            cookies.store_response(&self.url, headers);
        }
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

        if let Some(cookies) = self.cookies.as_mut() {
            cookies.remove_managed_header(&mut self.headers);
        }
        self.method = method.to_owned();
        self.url = url;
        self.headers = if let Some(auth) = self.auth.as_mut() {
            auth.on_redirect(body, header_policy)
        } else {
            redirect_headers(std::mem::take(&mut self.headers), body, header_policy)
        };
        if header_policy == RedirectHeaderPolicy::CrossOrigin {
            self.auth = None;
        }

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
            parts.ssrf_policy,
        )
        .map_err(|error| policy_error(&error))?;

        let auth = parts.auth.map(|provider| {
            RequestAuthState::new(
                provider,
                parts.headers.clone(),
                parts.auth_override_headers,
                parts.auth_removed_headers,
            )
        });
        let cookies = parts.cookie_jar.map(RequestCookieState::new);
        Ok(Self {
            method: parts.method.to_uppercase(),
            url,
            headers: parts.headers,
            body,
            body_policy,
            policy,
            cookies,
            auth,
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

fn normalized_header_names(names: Vec<String>) -> HashSet<String> {
    names
        .into_iter()
        .map(|name| name.to_ascii_lowercase())
        .collect()
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
