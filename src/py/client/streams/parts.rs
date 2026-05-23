use crate::core::client::ConnectionUseGuard;
use crate::core::headers::HeaderPairs;
use crate::core::metrics::{Metrics, ResponseBodyLifecycleOutcome};
use crate::py::client::acquire::AcquirePermit;
use crate::py::client::async_requests::RequestCompletion;
use crate::py::client::lifecycle::ResponseBodyLifecycle;
use crate::py::response::{RawRequestInfo, RawResponse};
use hyper::body::Incoming;
use std::sync::Arc;
use std::time::Duration;
use tokio::runtime::Handle;

pub(crate) struct RawStreamResponseParts {
    pub(crate) status_code: u16,
    pub(crate) headers: HeaderPairs,
    pub(crate) url: String,
    pub(crate) request: RawRequestInfo,
    pub(crate) http_version: String,
    pub(crate) elapsed: f64,
    pub(crate) history: Vec<RawResponse>,
    pub(crate) body: Incoming,
    pub(crate) permit: AcquirePermit,
    pub(crate) lifecycle: ResponseBodyLifecycle,
    pub(crate) connection_use: Option<ConnectionUseGuard>,
    pub(crate) successful_body_outcome: ResponseBodyLifecycleOutcome,
    pub(crate) metrics: Arc<Metrics>,
    pub(crate) completion: RequestCompletion,
    pub(crate) registry: super::registry::AsyncStreamRegistry,
    pub(crate) runtime_handle: Handle,
    pub(crate) read_timeout: Duration,
    pub(crate) read_timeout_secs: f64,
    pub(crate) origin: String,
    pub(crate) redirect_hop: usize,
}
