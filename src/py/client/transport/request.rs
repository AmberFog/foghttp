use super::errors::policy_error;
use crate::core::client::{ConnectionLimitContext, RequestWriteTimeoutContext};
use crate::core::headers::HeaderPairs;
use crate::core::numeric::duration_from_secs;
use crate::core::policy::{
    redirect_headers, PolicyMutation, PolicyPipeline, PolicyRequest, RequestBodyMutation,
    RequestBodyPolicy, ResponseHead, ResponsePolicyAction, TransportRoute,
};
use crate::core::request::{RequestBodyParts, RequestParts};
use crate::core::response::BufferedBodyBudget;
use crate::core::url::HttpUrl;
use crate::errors::FogHttpError;
use crate::py::client::upload_body::RawUploadBody;
use crate::py::response::RawRequestInfo;
use pyo3::prelude::*;
use std::time::Duration;

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
}

pub(super) struct RequestState {
    pub(super) method: String,
    pub(super) url: HttpUrl,
    pub(super) headers: HeaderPairs,
    pub(super) body: RequestBodyState,
    pub(super) body_policy: RequestBodyPolicy,
    policy: PolicyPipeline,
    pub(super) proxy_authorization: Option<String>,
    pub(super) total_timeout: f64,
    pub(super) read_timeout: f64,
    pub(super) write_timeout: Duration,
    pub(super) write_timeout_secs: f64,
    pub(super) max_response_body_size: Option<usize>,
    pub(super) buffered_body_budget: BufferedBodyBudget,
}

impl RequestState {
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

    pub(super) fn transport_route(&self) -> PyResult<TransportRoute> {
        self.policy
            .before_send(self.policy_request())
            .map_err(|error| policy_error(&error))
    }

    pub(super) fn on_response_headers(
        &self,
        status_code: u16,
        headers: &HeaderPairs,
    ) -> Option<ResponsePolicyAction> {
        self.policy.on_response_headers(
            self.policy_request(),
            ResponseHead::new(status_code, headers),
        )
    }

    pub(super) fn after_response_body(
        &mut self,
        action: ResponsePolicyAction,
        completed_redirects: usize,
    ) -> PyResult<()> {
        let mutation = self
            .policy
            .after_response_body(self.policy_request(), action, completed_redirects)
            .map_err(|error| policy_error(&error))?;
        self.apply_policy_mutation(mutation);
        Ok(())
    }

    fn policy_request(&self) -> PolicyRequest<'_> {
        PolicyRequest::new(&self.method, &self.url, self.body_policy)
    }

    fn apply_policy_mutation(&mut self, mutation: PolicyMutation) {
        let PolicyMutation::Redirect {
            body,
            method,
            remove_sensitive_headers,
            url,
        } = mutation;

        self.method = method.to_owned();
        self.url = url;
        self.headers = redirect_headers(
            std::mem::take(&mut self.headers),
            body,
            remove_sensitive_headers,
        );

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
        let policy = PolicyPipeline::new(
            &parts.proxy_policy,
            parts.use_proxy_transport,
            &url,
            parts.follow_redirects,
            parts.max_redirects,
        )
        .map_err(|error| policy_error(&error))?;

        Ok(Self {
            method: parts.method.to_uppercase(),
            url,
            headers: parts.headers,
            body,
            body_policy,
            policy,
            proxy_authorization: parts.proxy_authorization,
            total_timeout: parts.total_timeout,
            read_timeout: parts.read_timeout,
            write_timeout,
            write_timeout_secs: parts.write_timeout,
            max_response_body_size: parts.max_response_body_size,
            buffered_body_budget: parts.buffered_body_budget,
        })
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
