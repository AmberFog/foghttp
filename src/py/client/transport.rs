use crate::core::client::HyperClient;
use crate::core::headers::{response_headers, HeaderPairs};
use crate::core::request::{build_request, RequestParts};
use crate::core::response::{
    collect_body, decode_body, decoded_response_headers, BufferedBodyBudget,
};
use crate::core::url::HttpUrl;
use crate::errors::FogHttpError;
use crate::messages::{redirect_limit_exceeded, REQUEST_TOTAL_TIMEOUT};
use crate::py::client::acquire::AcquireGate;
use crate::py::client::redirects::{
    redirect_decision, redirect_headers, RedirectAction, RedirectDecision, RedirectHeaderPolicy,
};
use crate::py::client::timeout_diagnostics::{
    remaining_duration, timeout_error, TimeoutContext, TimeoutPhase,
};
use crate::py::response::{RawRequestInfo, RawResponse, RawResponseParts};
use hyper::body::Incoming;
use hyper::{Response, StatusCode};
use pyo3::prelude::*;
use std::time::Instant;

pub struct TransportRequest {
    pub method: String,
    pub url: String,
    pub headers: HeaderPairs,
    pub body: Option<Vec<u8>>,
    pub total_timeout: f64,
    pub max_response_body_size: Option<usize>,
    pub buffered_body_budget: BufferedBodyBudget,
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
            let redirect_hop = history.len();
            let origin = state.origin()?;
            let acquire_timeout_context = TimeoutContext::new(
                TimeoutPhase::PoolAcquire,
                started,
                state.total_timeout,
                &origin,
                redirect_hop,
            );
            let _permit = tokio::time::timeout(
                remaining_duration("Timeouts.total", &acquire_timeout_context)?,
                acquire_gate.acquire(&origin, pool_timeout, redirect_hop),
            )
            .await
            .map_err(|_| timeout_error(&acquire_timeout_context, REQUEST_TOTAL_TIMEOUT))??;
            let request_info = state.request_info();
            let request = build_request(state.request_parts())?;

            let response_headers_timeout_context = TimeoutContext::new(
                TimeoutPhase::ResponseHeaders,
                started,
                state.total_timeout,
                &origin,
                redirect_hop,
            );
            let response = tokio::time::timeout(
                remaining_duration("Timeouts.total", &response_headers_timeout_context)?,
                client.request(request),
            )
            .await
            .map_err(|_| timeout_error(&response_headers_timeout_context, REQUEST_TOTAL_TIMEOUT))?
            .map_err(|err| FogHttpError::new_err(err.to_string()))?;

            raw_response(
                response,
                request_info,
                RawResponseContext {
                    started,
                    total_timeout: state.total_timeout,
                    max_response_body_size: state.max_response_body_size,
                    buffered_body_budget: state.buffered_body_budget.clone(),
                    origin: &origin,
                    redirect_hop,
                },
            )
            .await?
        };

        let response_url = raw.request.url.clone();
        let redirect = if state.follow_redirects {
            redirect_decision(&state.method, &response_url, raw.status_code, &raw.headers)
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
        match redirect {
            RedirectDecision::Block(reason) => return Err(FogHttpError::new_err(reason)),
            RedirectDecision::Follow(action) => {
                history.push(raw);
                state.apply_redirect(action);
            }
        }
    }
}

struct RequestState {
    method: String,
    url: String,
    headers: HeaderPairs,
    body: Option<Vec<u8>>,
    total_timeout: f64,
    max_response_body_size: Option<usize>,
    buffered_body_budget: BufferedBodyBudget,
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
            buffered_body_budget: parts.buffered_body_budget,
            follow_redirects: parts.follow_redirects,
            max_redirects: parts.max_redirects,
        })
    }
}

async fn raw_response(
    response: Response<Incoming>,
    request: RawRequestInfo,
    context: RawResponseContext<'_>,
) -> PyResult<RawResponse> {
    let status = response.status();
    let status_code = status.as_u16();
    let http_version = format!("{:?}", response.version());
    let headers = response_headers(response.headers());
    let response_body_timeout_context = TimeoutContext::new(
        TimeoutPhase::ResponseBody,
        context.started,
        context.total_timeout,
        context.origin,
        context.redirect_hop,
    );
    let collected = tokio::time::timeout(
        remaining_duration("Timeouts.total", &response_body_timeout_context)?,
        collect_body(
            response.into_body(),
            context.max_response_body_size,
            context.buffered_body_budget,
        ),
    )
    .await
    .map_err(|_| timeout_error(&response_body_timeout_context, REQUEST_TOTAL_TIMEOUT))??;
    let (headers, response_content, body_reservation) =
        if response_body_can_be_decoded(&request.method, status) {
            let body = decode_body(collected, &headers, context.max_response_body_size)?;
            (
                decoded_response_headers(headers, body.decoded),
                body.content,
                body.reservation,
            )
        } else {
            (headers, collected.content, collected.reservation)
        };
    let url = request.url.clone();

    Ok(RawResponse::from_parts(RawResponseParts {
        status_code,
        headers,
        content: response_content,
        url,
        request,
        http_version,
        elapsed: context.started.elapsed().as_secs_f64(),
        history: Vec::new(),
        body_reservation: Some(body_reservation),
    }))
}

fn response_body_can_be_decoded(method: &str, status: StatusCode) -> bool {
    !method.eq_ignore_ascii_case("HEAD")
        && !status.is_informational()
        && !matches!(
            status,
            StatusCode::NO_CONTENT | StatusCode::RESET_CONTENT | StatusCode::NOT_MODIFIED
        )
}

struct RawResponseContext<'a> {
    started: Instant,
    total_timeout: f64,
    max_response_body_size: Option<usize>,
    buffered_body_budget: BufferedBodyBudget,
    origin: &'a str,
    redirect_hop: usize,
}
