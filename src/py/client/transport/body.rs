use super::context::RawResponseContext;
use crate::core::response::{BufferedBodyCollector, CollectedBody};
use crate::errors::FogHttpError;
use crate::messages::{REQUEST_TOTAL_TIMEOUT, RESPONSE_BODY_READ_TIMEOUT};
use crate::py::client::timeout_diagnostics::{
    read_timeout_error, remaining_duration, timeout_error, TimeoutContext, TimeoutPhase,
};
use bytes::Bytes;
use http_body_util::BodyExt;
use hyper::body::{Frame, Incoming};
use hyper::{Error as HyperError, StatusCode};
use pyo3::prelude::*;
use std::time::{Duration, Instant};

pub(super) fn response_body_can_be_decoded(method: &str, status: StatusCode) -> bool {
    !method.eq_ignore_ascii_case("HEAD")
        && !status.is_informational()
        && !matches!(
            status,
            StatusCode::NO_CONTENT | StatusCode::RESET_CONTENT | StatusCode::NOT_MODIFIED
        )
}

pub(super) async fn collect_response_body(
    mut body: Incoming,
    context: &RawResponseContext<'_>,
    read_timeout: Duration,
) -> PyResult<CollectedBody> {
    let mut collector = BufferedBodyCollector::new(
        &body,
        context.max_response_body_size,
        &context.buffered_body_budget,
    )?;

    while let Some(frame) = next_response_body_frame(&mut body, context, read_timeout).await? {
        let frame = frame.map_err(|err| FogHttpError::new_err(err.to_string()))?;
        let Ok(data) = frame.into_data() else {
            continue;
        };

        collector.push_data(&data)?;
    }

    Ok(collector.finish())
}

pub(super) async fn drain_response_body(
    mut body: Incoming,
    context: &RawResponseContext<'_>,
    read_timeout: Duration,
) -> PyResult<()> {
    while let Some(frame) = next_response_body_frame(&mut body, context, read_timeout).await? {
        frame.map_err(|err| FogHttpError::new_err(err.to_string()))?;
    }
    Ok(())
}

async fn next_response_body_frame(
    body: &mut Incoming,
    context: &RawResponseContext<'_>,
    read_timeout: Duration,
) -> PyResult<Option<Result<Frame<Bytes>, HyperError>>> {
    let total_timeout_context = TimeoutContext::new(
        TimeoutPhase::ResponseBody,
        context.started,
        context.total_timeout,
        context.origin,
        context.redirect_hop,
    );
    let read_timeout_context = TimeoutContext::new(
        TimeoutPhase::ResponseBody,
        Instant::now(),
        context.read_timeout,
        context.origin,
        context.redirect_hop,
    );
    tokio::time::timeout(
        remaining_duration("Timeouts.total", &total_timeout_context)?,
        tokio::time::timeout(read_timeout, body.frame()),
    )
    .await
    .map_err(|_| timeout_error(&total_timeout_context, REQUEST_TOTAL_TIMEOUT))?
    .map_err(|_| read_timeout_error(&read_timeout_context, RESPONSE_BODY_READ_TIMEOUT))
}
