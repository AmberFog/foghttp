mod future;
mod options;
mod redirects;
mod runtime;
mod transport;

use crate::core::client::{build_client, ClientOptions, HyperClient};
use crate::core::headers::HeaderPairs;
use crate::core::metrics::Metrics;
use crate::errors::FogHttpError;
use crate::py::client::future::complete_python_future;
use crate::py::client::options::validate_unsupported_options;
use crate::py::client::runtime::build_runtime;
use crate::py::client::transport::{send_request, TransportRequest};
use crate::py::response::RawResponse;
use crate::py::stats::RawStats;
use pyo3::prelude::*;
use pyo3::types::PyAny;
use std::sync::Arc;
use tokio::runtime::Runtime;

#[pyclass]
pub struct RawClient {
    client: Option<HyperClient>,
    runtime: Option<Runtime>,
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
        runtime_workers: Option<usize>,
    ) -> PyResult<Self> {
        validate_unsupported_options(trust_env)?;

        let client = build_client(ClientOptions {
            max_connections_per_host,
            idle_timeout,
            keepalive,
            connect_timeout,
        });
        let runtime = build_runtime(max_connections, runtime_workers)?;

        Ok(Self {
            client: Some(client),
            runtime: Some(runtime),
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
        headers: HeaderPairs,
        body: Option<Vec<u8>>,
        _connect_timeout: f64,
        total_timeout: f64,
    ) -> PyResult<RawResponse> {
        let client = self.client()?;
        let runtime = self.runtime()?;
        self.metrics.request_started();

        let result = py.detach(|| {
            runtime.block_on(send_request(
                client.clone(),
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
        headers: HeaderPairs,
        body: Option<Vec<u8>>,
        _connect_timeout: f64,
        total_timeout: f64,
    ) -> PyResult<Py<PyAny>> {
        let loop_ = py.import("asyncio")?.call_method0("get_running_loop")?;
        let future = loop_.call_method0("create_future")?;
        let loop_ = loop_.unbind();
        let future = future.unbind();
        let task_future = future.clone_ref(py);
        let client = self.client()?.clone();
        let metrics = Arc::clone(&self.metrics);
        let follow_redirects = self.follow_redirects;
        let max_redirects = self.max_redirects;
        let runtime = self.runtime()?;

        metrics.request_started();
        runtime.spawn(async move {
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

    fn close(&mut self) {
        self.close_resources();
    }
}

impl RawClient {
    fn client(&self) -> PyResult<&HyperClient> {
        self.client
            .as_ref()
            .ok_or_else(|| FogHttpError::new_err("client is closed"))
    }

    fn runtime(&self) -> PyResult<&Runtime> {
        self.runtime
            .as_ref()
            .ok_or_else(|| FogHttpError::new_err("client runtime is closed"))
    }

    fn close_resources(&mut self) {
        self.client.take();
        if let Some(runtime) = self.runtime.take() {
            runtime.shutdown_background();
        }
    }
}

impl Drop for RawClient {
    fn drop(&mut self) {
        self.close_resources();
    }
}
