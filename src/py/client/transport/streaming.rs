use super::client::TransportClients;
use super::context::{RawResponseContext, RawStreamResponseContext};
use super::request::{RequestState, TransportRequest};
use super::response::{raw_response, raw_stream_response};
use crate::core::headers::response_headers;
use crate::core::metrics::Metrics;
use crate::core::request::build_request;
use crate::errors::{transport_error_message, FogHttpError};
use crate::messages::{redirect_limit_exceeded, REQUEST_TOTAL_TIMEOUT};
use crate::py::client::acquire::AcquireGate;
use crate::py::client::async_requests::RequestCompletion;
use crate::py::client::redirects::{redirect_decision, RedirectDecision};
use crate::py::client::streams::{RawStreamResponse, StreamRegistry};
use crate::py::client::timeout_diagnostics::{
    remaining_duration, timeout_error, TimeoutContext, TimeoutPhase,
};
use hyper::HeaderMap;
use pyo3::prelude::*;
use std::sync::Arc;
use std::time::Instant;
use tokio::runtime::Handle;

#[allow(clippy::too_many_arguments)]
pub async fn send_stream_request(
    clients: TransportClients,
    acquire_gate: AcquireGate,
    metrics: Arc<Metrics>,
    active_streams: StreamRegistry,
    runtime_handle: Handle,
    pool_timeout: f64,
    parts: TransportRequest,
    completion: RequestCompletion,
) -> PyResult<RawStreamResponse> {
    let started = Instant::now();
    let mut state = RequestState::try_from(parts)?;
    let mut history = Vec::new();

    loop {
        let redirect_hop = history.len();
        let origin = state.origin()?;
        let acquire_timeout_context = TimeoutContext::new(
            TimeoutPhase::PoolAcquire,
            started,
            state.total_timeout,
            &origin,
            redirect_hop,
        );
        let permit = tokio::time::timeout(
            remaining_duration("Timeouts.total", &acquire_timeout_context)?,
            acquire_gate.acquire(&origin, pool_timeout, redirect_hop),
        )
        .await
        .map_err(|_| timeout_error(&acquire_timeout_context, REQUEST_TOTAL_TIMEOUT))??;
        let origin_metrics = permit.origin_metrics();
        let request_info = state.request_info();
        let use_http_proxy = state.use_http_proxy_for_current_url()?;
        let client = clients.select(use_http_proxy)?;
        let request = build_request(state.request_parts(use_http_proxy))?;

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
        .map_err(|err| FogHttpError::new_err(transport_error_message(&err)))?;

        let redirect = stream_redirect_decision(
            &state,
            &request_info.url,
            response.status().as_u16(),
            response.headers(),
        );

        let Some(redirect) = redirect else {
            return raw_stream_response(
                response,
                request_info,
                RawStreamResponseContext {
                    started,
                    read_timeout: state.read_timeout,
                    origin,
                    origin_metrics,
                    metrics,
                    active_streams,
                    runtime_handle,
                    completion,
                    permit,
                    redirect_hop,
                    history,
                },
            );
        };

        let raw = raw_response(
            response,
            request_info,
            RawResponseContext {
                started,
                total_timeout: state.total_timeout,
                read_timeout: state.read_timeout,
                max_response_body_size: state.max_response_body_size,
                buffered_body_budget: state.buffered_body_budget.clone(),
                origin: &origin,
                metrics: Arc::clone(&metrics),
                origin_metrics,
                redirect_hop,
            },
        )
        .await?;
        drop(permit);

        let response_url = raw.request.url.clone();
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
                state.apply_redirect(action)?;
            }
        }
    }
}

fn stream_redirect_decision(
    state: &RequestState,
    request_url: &str,
    status_code: u16,
    headers: &HeaderMap,
) -> Option<RedirectDecision> {
    if !state.follow_redirects {
        return None;
    }
    redirect_decision(
        &state.method,
        request_url,
        status_code,
        &response_headers(headers),
    )
}
