use crate::messages::RESPONSE_BODY_READ_TIMEOUT;
use crate::py::client::timeout_diagnostics::{read_timeout_error, TimeoutContext, TimeoutPhase};
use bytes::Bytes;
use http_body_util::BodyExt;
use hyper::body::{Frame, Incoming};
use hyper::Error as HyperError;
use pyo3::prelude::*;
use std::time::{Duration, Instant};

pub(super) async fn next_stream_body_frame(
    body: &mut Incoming,
    read_timeout: Duration,
    read_timeout_secs: f64,
    origin: &str,
    redirect_hop: usize,
) -> PyResult<Option<Result<Frame<Bytes>, HyperError>>> {
    let read_timeout_context = TimeoutContext::new(
        TimeoutPhase::ResponseBody,
        Instant::now(),
        read_timeout_secs,
        origin,
        redirect_hop,
    );
    tokio::time::timeout(read_timeout, body.frame())
        .await
        .map_err(|_| read_timeout_error(&read_timeout_context, RESPONSE_BODY_READ_TIMEOUT))
}
