use crate::core::metrics::{Metrics, OriginMetrics};
use crate::core::response::BufferedBodyBudget;
use crate::py::client::acquire::AcquirePermit;
use crate::py::client::async_requests::RequestCompletion;
use crate::py::client::streams::StreamRegistry;
use crate::py::response::RawResponse;
use std::sync::Arc;
use std::time::Instant;
use tokio::runtime::Handle;

pub(super) struct RawResponseContext<'a> {
    pub(super) started: Instant,
    pub(super) total_timeout: f64,
    pub(super) read_timeout: f64,
    pub(super) max_response_body_size: Option<usize>,
    pub(super) buffered_body_budget: BufferedBodyBudget,
    pub(super) origin: &'a str,
    pub(super) metrics: Arc<Metrics>,
    pub(super) origin_metrics: Arc<OriginMetrics>,
    pub(super) redirect_hop: usize,
}

pub(super) struct RawStreamResponseContext {
    pub(super) started: Instant,
    pub(super) read_timeout: f64,
    pub(super) origin: String,
    pub(super) origin_metrics: Arc<OriginMetrics>,
    pub(super) metrics: Arc<Metrics>,
    pub(super) active_streams: StreamRegistry,
    pub(super) runtime_handle: Handle,
    pub(super) completion: RequestCompletion,
    pub(super) permit: AcquirePermit,
    pub(super) redirect_hop: usize,
    pub(super) history: Vec<RawResponse>,
}
