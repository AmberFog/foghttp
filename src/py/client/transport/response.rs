use super::body::{collect_response_body, drain_response_body, response_body_can_be_decoded};
use super::context::{RawResponseContext, RawStreamResponseContext};
use crate::core::client::{ConnectionAbortReason, ConnectionTelemetry, ConnectionUseGuard};
use crate::core::headers::HeaderPairs;
use crate::core::metrics::{Metrics, OriginMetrics, ResponseBodyLifecycleOutcome};
use crate::core::numeric::duration_from_secs;
use crate::core::response::{decode_body, decoded_response_headers, response_body_decoding_plan};
use crate::core::telemetry::TelemetryErrorType;
use crate::errors::{
    FogHttpReadTimeoutError, FogHttpResponseBodyBudgetExceededError,
    FogHttpResponseBodyTooLargeError, FogHttpTimeoutError,
};
use crate::py::client::lifecycle::{successful_response_body_outcome, ResponseBodyLifecycle};
use crate::py::client::streams::{RawStreamResponse, RawStreamResponseParts};
use crate::py::response::{RawRequestInfo, RawResponse, RawResponseParts};
use hyper::body::Incoming;
use hyper::Response;
use pyo3::prelude::*;
use std::sync::Arc;

pub(super) struct ResponseLifecycleGuards {
    body: ResponseBodyLifecycle,
    connection_use: Option<ConnectionUseGuard>,
    successful_body_outcome: ResponseBodyLifecycleOutcome,
}

impl ResponseLifecycleGuards {
    pub(super) fn new(
        response: &Response<Incoming>,
        connection_use: Option<ConnectionUseGuard>,
        metrics: &Arc<Metrics>,
        origin_metrics: &Arc<OriginMetrics>,
    ) -> Self {
        let connection_use = connection_use.or_else(|| {
            response
                .extensions()
                .get::<ConnectionTelemetry>()
                .map(|telemetry| telemetry.request_started(None))
        });
        Self {
            body: ResponseBodyLifecycle::new(Arc::clone(metrics), Arc::clone(origin_metrics)),
            connection_use,
            successful_body_outcome: successful_response_body_outcome(
                response.version(),
                response.headers(),
            ),
        }
    }

    fn finish_connection(&mut self) {
        if let Some(connection_use) = self.connection_use.take() {
            connection_use.finish(self.successful_body_outcome);
        }
    }

    fn finish_body(&mut self) {
        self.body.finish(self.successful_body_outcome);
    }

    fn abort_connection(&mut self, error: &PyErr) {
        if let Some(connection_use) = self.connection_use.take() {
            connection_use.abort(ConnectionAbortReason::Error(Some(
                response_body_error_type(error),
            )));
        }
    }
}

pub(super) async fn drain_response(
    response: Response<Incoming>,
    mut lifecycle: ResponseLifecycleGuards,
    context: RawResponseContext<'_>,
) -> PyResult<()> {
    let read_timeout = duration_from_secs("Timeouts.read", context.read_timeout)
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
    if let Err(error) = drain_response_body(response.into_body(), &context, read_timeout).await {
        lifecycle.abort_connection(&error);
        return Err(error);
    }
    lifecycle.finish_connection();
    lifecycle.finish_body();
    Ok(())
}

pub(super) async fn raw_response(
    response: Response<Incoming>,
    request: RawRequestInfo,
    headers: HeaderPairs,
    mut lifecycle: ResponseLifecycleGuards,
    context: RawResponseContext<'_>,
) -> PyResult<RawResponse> {
    let status = response.status();
    let status_code = status.as_u16();
    let http_version = format!("{:?}", response.version());
    let decoding_plan = response_body_can_be_decoded(&request.method, status)
        .then(|| response_body_decoding_plan(response.headers()));
    let read_timeout = duration_from_secs("Timeouts.read", context.read_timeout)
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
    let collected = match collect_response_body(response.into_body(), &context, read_timeout).await
    {
        Ok(collected) => collected,
        Err(error) => {
            lifecycle.abort_connection(&error);
            return Err(error);
        }
    };
    lifecycle.finish_connection();
    let (headers, response_content, body_reservation) = if let Some(decoding_plan) = decoding_plan {
        let body = decode_body(collected, decoding_plan, context.max_response_body_size)?;
        (
            decoded_response_headers(headers, body.decoded),
            body.content,
            body.reservation,
        )
    } else {
        (headers, collected.content, collected.reservation)
    };
    lifecycle.finish_body();
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
        retry_trace: None,
        body_reservation: Some(body_reservation),
    }))
}

fn response_body_error_type(error: &PyErr) -> TelemetryErrorType {
    Python::attach(|py| {
        if error.is_instance_of::<FogHttpReadTimeoutError>(py) {
            TelemetryErrorType::ReadTimeout
        } else if error.is_instance_of::<FogHttpTimeoutError>(py) {
            TelemetryErrorType::TimeoutError
        } else if error.is_instance_of::<FogHttpResponseBodyTooLargeError>(py) {
            TelemetryErrorType::ResponseBodyTooLargeError
        } else if error.is_instance_of::<FogHttpResponseBodyBudgetExceededError>(py) {
            TelemetryErrorType::ResponseBodyBudgetExceededError
        } else {
            TelemetryErrorType::RequestError
        }
    })
}

pub(super) fn raw_stream_response(
    response: Response<Incoming>,
    request: RawRequestInfo,
    headers: HeaderPairs,
    lifecycle: ResponseLifecycleGuards,
    context: RawStreamResponseContext,
) -> PyResult<RawStreamResponse> {
    let status_code = response.status().as_u16();
    let http_version = format!("{:?}", response.version());
    let ResponseLifecycleGuards {
        body: lifecycle,
        connection_use,
        successful_body_outcome,
    } = lifecycle;
    let read_timeout = duration_from_secs("Timeouts.read", context.read_timeout)
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
    let url = request.url.clone();

    Ok(RawStreamResponse::from_parts(RawStreamResponseParts {
        status_code,
        headers,
        url,
        request,
        http_version,
        elapsed: context.started.elapsed().as_secs_f64(),
        history: context.history,
        retry_trace: None,
        body: response.into_body(),
        permit: context.permit,
        lifecycle,
        connection_use,
        successful_body_outcome,
        metrics: context.metrics,
        completion: context.completion,
        registry: context.active_streams,
        runtime_handle: context.runtime_handle,
        future_setters: context.future_setters,
        read_timeout,
        read_timeout_secs: context.read_timeout,
        origin: context.origin,
        redirect_hop: context.redirect_hop,
    }))
}
