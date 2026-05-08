mod future;
mod options;
mod runtime;
mod transport;

use crate::core::client::{build_client, ClientOptions, HyperClient};
use crate::core::metrics::Metrics;
use crate::py::client::future::complete_python_future;
use crate::py::client::options::validate_unsupported_options;
use crate::py::client::runtime::build_runtime;
use crate::py::client::transport::{send_request, TransportRequest};
use crate::py::response::RawResponse;
use crate::py::stats::RawStats;
use pyo3::prelude::*;
use pyo3::types::PyAny;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::runtime::Runtime;

#[pyclass]
pub struct RawClient {
    client: HyperClient,
    runtime: Runtime,
    metrics: Arc<Metrics>,
    follow_redirects: bool,
    max_redirects: usize,
}

#[pymethods]
impl RawClient {
    #[new]
    #[allow(clippy::too_many_arguments)]
    fn new(
        max_connections: usize,
        max_connections_per_host: usize,
        idle_timeout: f64,
        keepalive: bool,
        connect_timeout: f64,
        follow_redirects: bool,
        max_redirects: usize,
        trust_env: bool,
    ) -> PyResult<Self> {
        validate_unsupported_options(trust_env)?;

        let client = build_client(ClientOptions {
            max_connections_per_host,
            idle_timeout,
            keepalive,
            connect_timeout,
        });
        let runtime = build_runtime(max_connections)?;

        Ok(Self {
            client,
            runtime,
            metrics: Arc::new(Metrics::default()),
            follow_redirects,
            max_redirects,
        })
    }

    #[allow(clippy::too_many_arguments)]
    fn request(
        &self,
        py: Python<'_>,
        method: String,
        url: String,
        headers: HashMap<String, String>,
        body: Option<Vec<u8>>,
        _connect_timeout: f64,
        total_timeout: f64,
    ) -> PyResult<RawResponse> {
        self.metrics.request_started();

        let result = py.detach(|| {
            self.runtime.block_on(send_request(
                self.client.clone(),
                TransportRequest {
                    method,
                    url,
                    headers,
                    body,
                    total_timeout,
                    follow_redirects: self.follow_redirects,
                    max_redirects: self.max_redirects,
                },
            ))
        });

        self.metrics.request_finished(result.is_err());
        result
    }

    #[allow(clippy::too_many_arguments)]
    fn request_async(
        &self,
        py: Python<'_>,
        method: String,
        url: String,
        headers: HashMap<String, String>,
        body: Option<Vec<u8>>,
        _connect_timeout: f64,
        total_timeout: f64,
    ) -> PyResult<Py<PyAny>> {
        let loop_ = py.import("asyncio")?.call_method0("get_running_loop")?;
        let future = loop_.call_method0("create_future")?;
        let loop_ = loop_.unbind();
        let future = future.unbind();
        let task_future = future.clone_ref(py);
        let client = self.client.clone();
        let metrics = Arc::clone(&self.metrics);
        let follow_redirects = self.follow_redirects;
        let max_redirects = self.max_redirects;

        metrics.request_started();
        self.runtime.spawn(async move {
            let result = send_request(
                client,
                TransportRequest {
                    method,
                    url,
                    headers,
                    body,
                    total_timeout,
                    follow_redirects,
                    max_redirects,
                },
            )
            .await;
            metrics.request_finished(result.is_err());
            complete_python_future(&loop_, &task_future, result);
        });

        Ok(future)
    }

    fn stats(&self) -> RawStats {
        self.metrics.snapshot().into()
    }
}
