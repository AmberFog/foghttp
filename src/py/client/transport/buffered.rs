use super::client::TransportClients;
use super::context::RawResponseContext;
use super::request::{RequestState, TransportRequest};
use super::response::raw_response;
use crate::core::metrics::Metrics;
use crate::core::request::build_request;
use crate::errors::FogHttpError;
use crate::messages::{redirect_limit_exceeded, REQUEST_TOTAL_TIMEOUT};
use crate::py::client::acquire::AcquireGate;
use crate::py::client::redirects::{redirect_decision, RedirectDecision};
use crate::py::client::timeout_diagnostics::{
    remaining_duration, timeout_error, TimeoutContext, TimeoutPhase,
};
use crate::py::response::RawResponse;
use pyo3::prelude::*;
use std::sync::Arc;
use std::time::Instant;

pub async fn send_request(
    clients: TransportClients,
    acquire_gate: AcquireGate,
    metrics: Arc<Metrics>,
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
            .map_err(|err| FogHttpError::new_err(err.to_string()))?;

            raw_response(
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
                state.apply_redirect(action)?;
            }
        }
    }
}
