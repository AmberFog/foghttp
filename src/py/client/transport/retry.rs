use super::context::RawResponseContext;
use super::request::{PendingRetryDecision, RequestState, RetryAction};
use super::response::{drain_response, ResponseLifecycleGuards};
use crate::messages::REQUEST_TOTAL_TIMEOUT;
use crate::py::client::acquire::AcquirePermit;
use crate::py::client::timeout_diagnostics::{
    remaining_duration, timeout_error, TimeoutContext, TimeoutPhase,
};
use hyper::body::Incoming;
use hyper::Response;
use pyo3::prelude::*;
use std::time::{Duration, Instant};

pub(super) async fn retry_after_network_error(
    state: &mut RequestState,
    retryable: bool,
    permit: AcquirePermit,
    started: Instant,
    origin: &str,
    redirect_hop: usize,
) -> PyResult<bool> {
    if !retryable {
        return Ok(false);
    }
    let Some(pending) = state.retry_on_network_error() else {
        return Ok(false);
    };
    let action = state.commit_retry_decision(&pending, started.elapsed(), redirect_hop);
    let RetryAction::Retry(delay) = action else {
        return Ok(false);
    };

    drop(permit);
    wait_for_retry(delay, started, state.total_timeout, origin, redirect_hop).await?;
    state.advance_retry_attempt();
    Ok(true)
}

pub(super) async fn retry_after_response(
    state: &mut RequestState,
    pending: &PendingRetryDecision,
    response: Response<Incoming>,
    response_lifecycle: ResponseLifecycleGuards,
    context: RawResponseContext<'_>,
    permit: AcquirePermit,
) -> PyResult<()> {
    let started = context.started;
    let total_timeout = context.total_timeout;
    let origin = context.origin;
    let redirect_hop = context.redirect_hop;
    drain_response(response, response_lifecycle, context).await?;
    drop(permit);

    let RetryAction::Retry(delay) =
        state.commit_retry_decision(pending, started.elapsed(), redirect_hop)
    else {
        unreachable!("pending retry changed after response drain");
    };
    wait_for_retry(delay, started, total_timeout, origin, redirect_hop).await?;
    state.advance_retry_attempt();
    Ok(())
}

pub(super) async fn wait_for_retry(
    delay: Duration,
    started: Instant,
    total_timeout: f64,
    origin: &str,
    redirect_hop: usize,
) -> PyResult<()> {
    let context = TimeoutContext::new(
        TimeoutPhase::RetryBackoff,
        started,
        total_timeout,
        origin,
        redirect_hop,
    );
    tokio::time::timeout(
        remaining_duration("Timeouts.total", &context)?,
        tokio::time::sleep(delay),
    )
    .await
    .map_err(|_| timeout_error(&context, REQUEST_TOTAL_TIMEOUT))
}
