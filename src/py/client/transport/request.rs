use crate::core::client::RequestWriteTimeoutContext;
use crate::core::headers::HeaderPairs;
use crate::core::numeric::duration_from_secs;
use crate::core::request::RequestParts;
use crate::core::response::BufferedBodyBudget;
use crate::core::url::HttpUrl;
use crate::errors::FogHttpError;
use crate::messages::NON_REPLAYABLE_REQUEST_BODY_REDIRECT;
use crate::py::client::body::BodyReplayability;
use crate::py::client::redirects::{redirect_headers, RedirectAction, RedirectHeaderPolicy};
use crate::py::client::transport::proxy::ProxyTransportPolicy;
use crate::py::response::RawRequestInfo;
use pyo3::prelude::*;
use std::time::Duration;

pub struct TransportRequest {
    pub method: String,
    pub url: String,
    pub headers: HeaderPairs,
    pub body: Option<Vec<u8>>,
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
    pub(super) url: String,
    pub(super) headers: HeaderPairs,
    pub(super) body: Option<Vec<u8>>,
    pub(super) body_replayability: BodyReplayability,
    pub(super) use_proxy_transport: bool,
    pub(super) proxy_policy: ProxyTransportPolicy,
    pub(super) initial_origin: String,
    pub(super) proxy_authorization: Option<String>,
    pub(super) total_timeout: f64,
    pub(super) read_timeout: f64,
    pub(super) write_timeout: Duration,
    pub(super) write_timeout_secs: f64,
    pub(super) max_response_body_size: Option<usize>,
    pub(super) buffered_body_budget: BufferedBodyBudget,
    pub(super) follow_redirects: bool,
    pub(super) max_redirects: usize,
}

impl RequestState {
    pub(super) fn request_parts(&self, use_proxy_transport: bool) -> RequestParts {
        RequestParts {
            method: self.method.clone(),
            url: self.url.clone(),
            headers: self.headers.clone(),
            body: self.body.clone(),
            proxy_authorization: self.plain_http_proxy_authorization(use_proxy_transport),
        }
    }

    fn plain_http_proxy_authorization(&self, use_proxy_transport: bool) -> Option<String> {
        let is_plain_http = HttpUrl::parse(&self.url).is_ok_and(|url| url.scheme() == "http");
        if use_proxy_transport && is_plain_http {
            return self.proxy_authorization.clone();
        }
        None
    }

    pub(super) fn request_info(&self) -> RawRequestInfo {
        RawRequestInfo {
            method: self.method.clone(),
            url: self.url.clone(),
            headers: self.headers.clone(),
        }
    }

    pub(super) fn origin(&self) -> PyResult<String> {
        HttpUrl::parse(&self.url)
            .map(|url| url.origin())
            .map_err(FogHttpError::new_err)
    }

    pub(super) fn has_request_body(&self) -> bool {
        self.body.as_ref().is_some_and(|body| !body.is_empty())
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

    pub(super) fn use_proxy_transport_for_current_url(&self) -> PyResult<bool> {
        let url = HttpUrl::parse(&self.url).map_err(FogHttpError::new_err)?;
        self.proxy_policy
            .use_proxy_transport(self.use_proxy_transport, &self.initial_origin, &url)
    }

    pub(super) fn apply_redirect(&mut self, redirect: RedirectAction) -> PyResult<()> {
        if redirect.preserve_body && self.body.is_some() && !self.body_replayability.can_replay() {
            return Err(FogHttpError::new_err(NON_REPLAYABLE_REQUEST_BODY_REDIRECT));
        }

        let next_url = HttpUrl::parse(&redirect.url).map_err(FogHttpError::new_err)?;
        self.proxy_policy
            .validate_redirect(&self.initial_origin, &next_url)?;

        self.method = redirect.method;
        next_url.as_str().clone_into(&mut self.url);
        self.headers = redirect_headers(
            std::mem::take(&mut self.headers),
            RedirectHeaderPolicy {
                preserve_body: redirect.preserve_body,
                remove_sensitive_headers: redirect.remove_sensitive_headers,
            },
        );

        if !redirect.preserve_body {
            self.body = None;
            self.body_replayability = BodyReplayability::Replayable;
        }
        Ok(())
    }

    pub(super) fn try_from(parts: TransportRequest) -> PyResult<Self> {
        let url = HttpUrl::parse(&parts.url).map_err(FogHttpError::new_err)?;
        let write_timeout = duration_from_secs("Timeouts.write", parts.write_timeout)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let body_replayability =
            BodyReplayability::from_buffered_body(parts.body.as_deref(), parts.body_replayable);
        let proxy_policy = ProxyTransportPolicy::parse(&parts.proxy_policy)?;

        Ok(Self {
            method: parts.method.to_uppercase(),
            url: url.as_str().to_owned(),
            headers: parts.headers,
            body: parts.body,
            body_replayability,
            use_proxy_transport: parts.use_proxy_transport,
            proxy_policy,
            initial_origin: url.origin(),
            proxy_authorization: parts.proxy_authorization,
            total_timeout: parts.total_timeout,
            read_timeout: parts.read_timeout,
            write_timeout,
            write_timeout_secs: parts.write_timeout,
            max_response_body_size: parts.max_response_body_size,
            buffered_body_budget: parts.buffered_body_budget,
            follow_redirects: parts.follow_redirects,
            max_redirects: parts.max_redirects,
        })
    }
}
