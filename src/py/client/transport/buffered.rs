use super::client::TransportClients;
use super::context::RawResponseContext;
use super::errors::transport_error;
use super::request::{RequestState, TransportRequest};
use super::response::{raw_response, ResponseLifecycleGuards};
use crate::core::client::{with_connection_limit_timeout, with_request_write_timeout};
use crate::core::headers::response_headers;
use crate::core::metrics::Metrics;
use crate::core::request::build_request;
use crate::messages::REQUEST_TOTAL_TIMEOUT;
use crate::py::client::acquire::AcquireGate;
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
        let (mut raw, response_action) = {
            let redirect_hop = history.len();
            let route = state.transport_route(redirect_hop)?;
            let origin = state.origin();
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

            let response_headers_timeout_context = TimeoutContext::new(
                TimeoutPhase::ResponseHeaders,
                started,
                state.total_timeout,
                &origin,
                redirect_hop,
            );
            let write_timeout_context = state.write_timeout_context(&origin, redirect_hop);
            let connection_limit_context =
                RequestState::connection_limit_context(&origin, redirect_hop, pool_timeout)?;
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
            .map_err(|_| timeout_error(&response_headers_timeout_context, REQUEST_TOTAL_TIMEOUT))?
            .map_err(|err| transport_error(&err))?;

            let response_lifecycle =
                ResponseLifecycleGuards::new(&response, &metrics, &origin_metrics);
            let headers = response_headers(response.headers());
            let response_action =
                state.on_response_headers(response.status().as_u16(), &headers, redirect_hop)?;
            let raw = raw_response(
                response,
                request_info,
                headers,
                response_lifecycle,
                RawResponseContext {
                    started,
                    total_timeout: state.total_timeout,
                    read_timeout: state.read_timeout,
                    max_response_body_size: state.max_response_body_size,
                    buffered_body_budget: state.buffered_body_budget.clone(),
                    origin: &origin,
                    redirect_hop,
                },
            )
            .await?;
            (raw, response_action)
        };

        let Some(action) = response_action else {
            raw.history = history;
            return Ok(raw);
        };
        state.after_response_body(action, history.len())?;
        history.push(raw);
    }
}
