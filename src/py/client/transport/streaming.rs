use super::client::TransportClients;
use super::context::RawStreamResponseContext;
use super::errors::{is_retryable_network_error, transport_error};
use super::request::{acquire_request_slot, send_current_hop, RequestState, TransportRequest};
use super::response::{raw_response, raw_stream_response, ResponseLifecycleGuards};
use super::retry::{retry_after_network_error, retry_after_response};
use crate::core::headers::response_headers;
use crate::core::metrics::Metrics;
use crate::py::client::acquire::AcquireGate;
use crate::py::client::async_requests::RequestCompletion;
use crate::py::client::future::PythonFutureSetters;
use crate::py::client::streams::{RawStreamResponse, StreamRegistry};
use crate::py::retry::{attach_retry_trace, RetryAttemptCompletion, RetryTraceOutcome};
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
    future_setters: PythonFutureSetters,
    parts: TransportRequest,
    completion: RequestCompletion,
) -> PyResult<RawStreamResponse> {
    let started = Instant::now();
    let mut state = RequestState::try_from(parts)?;
    let mut history = Vec::new();
    let result = send_stream_request_attempts(
        &clients,
        &acquire_gate,
        &metrics,
        active_streams,
        runtime_handle,
        pool_timeout,
        future_setters,
        started,
        &mut state,
        &mut history,
        completion,
    )
    .await;
    let trace = match result.as_ref() {
        Ok(response) => state.finish_retry_trace(
            RetryTraceOutcome::Response,
            Some(response.terminal_status_code()),
            response.redirect_hop(),
            started.elapsed(),
        ),
        Err(_) => state.finish_retry_trace(
            RetryTraceOutcome::Error,
            None,
            history.len(),
            started.elapsed(),
        ),
    };
    match result {
        Ok(mut response) => {
            response.set_retry_trace(trace);
            Ok(response)
        }
        Err(error) => Err(attach_retry_trace(error, trace)),
    }
}

#[allow(
    clippy::too_many_arguments,
    clippy::too_many_lines,
    reason = "attempt loop owns one logical stream lifecycle"
)]
async fn send_stream_request_attempts(
    clients: &TransportClients,
    acquire_gate: &AcquireGate,
    metrics: &Arc<Metrics>,
    active_streams: StreamRegistry,
    runtime_handle: Handle,
    pool_timeout: f64,
    future_setters: PythonFutureSetters,
    started: Instant,
    state: &mut RequestState,
    history: &mut Vec<crate::py::response::RawResponse>,
    completion: RequestCompletion,
) -> PyResult<RawStreamResponse> {
    loop {
        state.begin_transport_hop();
        let redirect_hop = history.len();
        let route = state.transport_route(redirect_hop)?;
        let origin = state.origin();
        let permit = acquire_request_slot(
            acquire_gate,
            &origin,
            pool_timeout,
            started,
            state.total_timeout,
            redirect_hop,
        )
        .await?;
        let origin_metrics = permit.origin_metrics();
        let response = send_current_hop(
            clients,
            state,
            &origin,
            redirect_hop,
            pool_timeout,
            started,
            route,
        )
        .await?;
        let (response, request_info) = match response {
            Ok(response) => response,
            Err(error) => {
                if retry_after_network_error(
                    state,
                    is_retryable_network_error(&error),
                    permit,
                    started,
                    &origin,
                    redirect_hop,
                )
                .await?
                {
                    continue;
                }
                return Err(transport_error(&error));
            }
        };

        let response_lifecycle = ResponseLifecycleGuards::new(&response, metrics, &origin_metrics);
        let headers = response_headers(response.headers());
        let status_code = response.status().as_u16();
        let response_action = state.on_response_headers(status_code, &headers, redirect_hop)?;
        let retry_decision = response_action
            .is_none()
            .then(|| state.retry_on_response(status_code, &headers))
            .flatten();

        if let Some(pending) = retry_decision {
            if pending.should_retry() {
                retry_after_response(
                    state,
                    &pending,
                    response,
                    response_lifecycle,
                    state.response_context(started, &origin, redirect_hop),
                    permit,
                )
                .await?;
                continue;
            }
            state.commit_retry_decision(
                &pending,
                started.elapsed(),
                redirect_hop,
                RetryAttemptCompletion::Complete,
            );
        }

        let Some(response_action) = response_action else {
            return raw_stream_response(
                response,
                request_info,
                headers,
                response_lifecycle,
                RawStreamResponseContext {
                    started,
                    read_timeout: state.read_timeout,
                    origin,
                    metrics: Arc::clone(metrics),
                    active_streams,
                    runtime_handle,
                    completion,
                    permit,
                    future_setters,
                    redirect_hop,
                    history: std::mem::take(history),
                },
            );
        };

        let raw = raw_response(
            response,
            request_info,
            headers,
            response_lifecycle,
            state.response_context(started, &origin, redirect_hop),
        )
        .await?;
        drop(permit);

        state.after_response_body(response_action, history.len())?;
        history.push(raw);
    }
}
