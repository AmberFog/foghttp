use crate::core::client::HyperClient;
use crate::core::headers::{response_headers, HeaderPairs};
use crate::core::request::{build_request, RequestParts};
use crate::core::response::collect_body;
use crate::core::url::HttpUrl;
use crate::errors::{FogHttpError, FogHttpTimeoutError};
use crate::messages::{redirect_limit_exceeded, REQUEST_TOTAL_TIMEOUT};
use crate::py::client::acquire::AcquireGate;
use crate::py::client::redirects::{
    redirect_action, redirect_headers, RedirectAction, RedirectHeaderPolicy,
};
use crate::py::response::{RawRequestInfo, RawResponse};
use hyper::body::Incoming;
use hyper::Response;
use pyo3::prelude::*;
use std::time::{Duration, Instant};

pub struct TransportRequest {
    pub method: String,
    pub url: String,
    pub headers: HeaderPairs,
    pub body: Option<Vec<u8>>,
    pub total_timeout: f64,
    pub max_response_body_size: Option<usize>,
    pub follow_redirects: bool,
    pub max_redirects: usize,
}

pub async fn send_request(
    client: HyperClient,
    acquire_gate: AcquireGate,
    pool_timeout: f64,
    parts: TransportRequest,
) -> PyResult<RawResponse> {
    let started = Instant::now();
    let mut state = RequestState::try_from(parts)?;
    let mut history = Vec::new();

    loop {
        let mut raw = {
            let origin = state.origin()?;
            let _permit = acquire_gate.acquire(&origin, pool_timeout).await?;
            let request_info = state.request_info();
            let request = build_request(state.request_parts())?;

            let response = tokio::time::timeout(
                remaining_duration(state.total_timeout, started),
                client.request(request),
            )
            .await
            .map_err(|_| FogHttpTimeoutError::new_err(REQUEST_TOTAL_TIMEOUT))?
            .map_err(|err| FogHttpError::new_err(err.to_string()))?;

            raw_response(
                response,
                request_info,
                started,
                state.max_response_body_size,
            )
            .await?
        };

        let response_url = raw.request.url.clone();
        let redirect = if state.follow_redirects {
            redirect_action(&state.method, &response_url, raw.status_code, &raw.headers)
        } else {
            None
        };

        let Some(redirect) = redirect else {
            raw.history = history;
            return Ok(raw);
        };
        if history.len() >= state.max_redirects {
            return Err(FogHttpError::new_err(redirect_limit_exceeded(
                state.max_redirects,
                &response_url,
            )));
        }

        history.push(raw);
        state.apply_redirect(redirect);
    }
}

struct RequestState {
    method: String,
    url: String,
    headers: HeaderPairs,
    body: Option<Vec<u8>>,
    total_timeout: f64,
    max_response_body_size: Option<usize>,
    follow_redirects: bool,
    max_redirects: usize,
}

impl RequestState {
    fn request_parts(&self) -> RequestParts {
        RequestParts {
            method: self.method.clone(),
            url: self.url.clone(),
            headers: self.headers.clone(),
            body: self.body.clone(),
        }
    }

    fn request_info(&self) -> RawRequestInfo {
        RawRequestInfo {
            method: self.method.clone(),
            url: self.url.clone(),
            headers: self.headers.clone(),
        }
    }

    fn origin(&self) -> PyResult<String> {
        HttpUrl::parse(&self.url)
            .map(|url| url.origin())
            .map_err(FogHttpError::new_err)
    }

    fn apply_redirect(&mut self, redirect: RedirectAction) {
        self.method = redirect.method;
        self.url = redirect.url;
        self.headers = redirect_headers(
            std::mem::take(&mut self.headers),
            RedirectHeaderPolicy {
                preserve_body: redirect.preserve_body,
                remove_sensitive_headers: redirect.remove_sensitive_headers,
            },
        );

        if !redirect.preserve_body {
            self.body = None;
        }
    }
}

impl RequestState {
    fn try_from(parts: TransportRequest) -> PyResult<Self> {
        let url = HttpUrl::parse(&parts.url).map_err(FogHttpError::new_err)?;

        Ok(Self {
            method: parts.method.to_uppercase(),
            url: url.as_str().to_owned(),
            headers: parts.headers,
            body: parts.body,
            total_timeout: parts.total_timeout,
            max_response_body_size: parts.max_response_body_size,
            follow_redirects: parts.follow_redirects,
            max_redirects: parts.max_redirects,
        })
    }
}

async fn raw_response(
    response: Response<Incoming>,
    request: RawRequestInfo,
    started: Instant,
    max_response_body_size: Option<usize>,
) -> PyResult<RawResponse> {
    let status_code = response.status().as_u16();
    let http_version = format!("{:?}", response.version());
    let headers = response_headers(response.headers());
    let content = collect_body(response.into_body(), max_response_body_size).await?;
    let url = request.url.clone();

    Ok(RawResponse {
        status_code,
        headers,
        content,
        url,
        request,
        http_version,
        elapsed: started.elapsed().as_secs_f64(),
        history: Vec::new(),
    })
}

fn remaining_duration(total_timeout: f64, started: Instant) -> Duration {
    Duration::from_secs_f64(total_timeout.max(0.0)).saturating_sub(started.elapsed())
}
