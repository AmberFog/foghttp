use super::body::{collect_response_body, response_body_can_be_decoded};
use super::context::{RawResponseContext, RawStreamResponseContext};
use crate::core::client::ConnectionTelemetry;
use crate::core::headers::response_headers;
use crate::core::numeric::duration_from_secs;
use crate::core::response::{decode_body, decoded_response_headers, response_body_decoding_plan};
use crate::py::client::lifecycle::{successful_response_body_outcome, ResponseBodyLifecycle};
use crate::py::client::streams::{RawStreamResponse, RawStreamResponseParts};
use crate::py::response::{RawRequestInfo, RawResponse, RawResponseParts};
use hyper::body::Incoming;
use hyper::Response;
use pyo3::prelude::*;
use std::sync::Arc;

pub(super) async fn raw_response(
    response: Response<Incoming>,
    request: RawRequestInfo,
    context: RawResponseContext<'_>,
) -> PyResult<RawResponse> {
    let status = response.status();
    let status_code = status.as_u16();
    let http_version = format!("{:?}", response.version());
    let successful_body_outcome =
        successful_response_body_outcome(response.version(), response.headers());
    let decoding_plan = response_body_can_be_decoded(&request.method, status)
        .then(|| response_body_decoding_plan(response.headers()));
    let headers = response_headers(response.headers());
    let mut connection_use = response
        .extensions()
        .get::<ConnectionTelemetry>()
        .map(ConnectionTelemetry::response_started);
    let mut lifecycle = ResponseBodyLifecycle::new(
        Arc::clone(&context.metrics),
        Arc::clone(&context.origin_metrics),
    );
    let read_timeout = duration_from_secs("Timeouts.read", context.read_timeout)
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
    let collected = collect_response_body(response.into_body(), &context, read_timeout).await?;
    if let Some(connection_use) = connection_use.take() {
        connection_use.finish(successful_body_outcome);
    }
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
    lifecycle.finish(successful_body_outcome);
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

pub(super) fn raw_stream_response(
    response: Response<Incoming>,
    request: RawRequestInfo,
    context: RawStreamResponseContext,
) -> PyResult<RawStreamResponse> {
    let status_code = response.status().as_u16();
    let http_version = format!("{:?}", response.version());
    let successful_body_outcome =
        successful_response_body_outcome(response.version(), response.headers());
    let headers = response_headers(response.headers());
    let connection_use = response
        .extensions()
        .get::<ConnectionTelemetry>()
        .map(ConnectionTelemetry::response_started);
    let lifecycle = ResponseBodyLifecycle::new(
        Arc::clone(&context.metrics),
        Arc::clone(&context.origin_metrics),
    );
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
