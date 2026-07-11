use super::client::TransportClients;
use super::context::{RawResponseContext, RawStreamResponseContext};
use super::errors::transport_error;
use super::request::{RequestState, TransportRequest};
use super::response::{raw_response, raw_stream_response, ResponseLifecycleGuards};
use crate::core::client::{with_connection_limit_timeout, with_request_write_timeout};
use crate::core::headers::response_headers;
use crate::core::metrics::Metrics;
use crate::core::request::build_request;
use crate::messages::REQUEST_TOTAL_TIMEOUT;
use crate::py::client::acquire::AcquireGate;
use crate::py::client::async_requests::RequestCompletion;
use crate::py::client::future::PythonFutureSetters;
use crate::py::client::streams::{RawStreamResponse, StreamRegistry};
use crate::py::client::timeout_diagnostics::{
    remaining_duration, timeout_error, TimeoutContext, TimeoutPhase,
};
use hyper::body::Incoming;
use hyper::Response;
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

    loop {
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
        let (response, request_info) = send_current_hop(
            &clients,
            &mut state,
            &origin,
            redirect_hop,
            pool_timeout,
            started,
            route,
        )
        .await?;

        let response_lifecycle = ResponseLifecycleGuards::new(&response, &metrics, &origin_metrics);
        let headers = response_headers(response.headers());
        let response_action =
            state.on_response_headers(response.status().as_u16(), &headers, redirect_hop)?;

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
                    metrics,
                    active_streams,
                    runtime_handle,
                    completion,
                    permit,
                    future_setters,
                    redirect_hop,
                    history,
                },
            );
        };

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
        drop(permit);

        state.after_response_body(response_action, history.len())?;
        history.push(raw);
    }
}

async fn send_current_hop(
    clients: &TransportClients,
    state: &mut RequestState,
    origin: &str,
    redirect_hop: usize,
    pool_timeout: f64,
    started: Instant,
    route: crate::core::policy::TransportRoute,
) -> PyResult<(Response<Incoming>, crate::py::response::RawRequestInfo)> {
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
    .map_err(|_| timeout_error(&response_headers_timeout_context, REQUEST_TOTAL_TIMEOUT))?
    .map_err(|err| transport_error(&err))?;

    Ok((response, request_info))
}
