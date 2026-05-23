pub(crate) mod acquire;
mod async_requests;
mod body;
mod future;
mod lifecycle;
mod options;
mod redirects;
mod runtime;
mod timeout_diagnostics;
mod transport;

use crate::core::client::{build_client, ClientOptions, HyperClient};
use crate::core::headers::HeaderPairs;
use crate::core::metrics::Metrics;
use crate::core::response::BufferedBodyBudget;
use crate::errors::FogHttpError;
use crate::py::client::acquire::AcquireGate;
use crate::py::client::async_requests::{
    spawn_async_request, AsyncRequestRegistry, AsyncRequestSpawn,
};
use crate::py::client::options::{
    validate_numeric_client_options, validate_request_timeouts, validate_unsupported_options,
    NumericClientOptions,
};
use crate::py::client::runtime::build_runtime;
use crate::py::client::transport::{send_request, TransportRequest};
use crate::py::response::RawResponse;
use crate::py::stats::RawStats;
use crate::py::{RawPoolDiagnostics, RawTransportState};
use pyo3::prelude::*;
use pyo3::types::PyAny;
use std::sync::Arc;
use tokio::runtime::Runtime;

#[pyclass]
pub struct RawClient {
    client: Option<HyperClient>,
    runtime: Option<Runtime>,
    acquire_gate: AcquireGate,
    metrics: Arc<Metrics>,
    active_async_requests: AsyncRequestRegistry,
    max_response_body_size: Option<usize>,
    buffered_body_budget: BufferedBodyBudget,
    follow_redirects: bool,
    max_redirects: usize,
}

#[pymethods]
impl RawClient {
    #[new]
    // The private PyO3 boundary mirrors Python client options. Internally we
    // group these values into typed option structs before building transport.
    #[allow(clippy::fn_params_excessive_bools, clippy::too_many_arguments)]
    fn new(
        max_active_requests: usize,
        max_active_requests_per_origin: Option<usize>,
        max_idle_connections_per_host: usize,
        max_pending_requests: usize,
        max_response_body_size: Option<usize>,
        max_buffered_response_bytes: Option<usize>,
        idle_timeout: f64,
        keepalive: bool,
        connect_timeout: f64,
        follow_redirects: bool,
        max_redirects: usize,
        ca_certificates: Vec<Vec<u8>>,
        trust_webpki_roots: bool,
        trust_env: bool,
        runtime_workers: Option<usize>,
    ) -> PyResult<Self> {
        validate_unsupported_options(trust_env)?;
        validate_numeric_client_options(NumericClientOptions {
            max_active_requests,
            max_active_requests_per_origin,
            max_idle_connections_per_host,
            max_pending_requests,
            max_response_body_size,
            max_buffered_response_bytes,
            idle_timeout,
            connect_timeout,
        })?;

        let metrics = Arc::new(Metrics::default());
        let client_options = ClientOptions {
            max_idle_connections_per_host,
            idle_timeout,
            keepalive,
            connect_timeout,
            ca_certificates,
            trust_webpki_roots,
        };
        let client =
            build_client(&client_options, Arc::clone(&metrics)).map_err(FogHttpError::new_err)?;
        let runtime = build_runtime(max_active_requests, runtime_workers)?;
        let buffered_body_budget =
            BufferedBodyBudget::new(max_buffered_response_bytes, Arc::clone(&metrics));
        let acquire_gate = AcquireGate::new(
            max_active_requests,
            max_active_requests_per_origin,
            max_pending_requests,
            Arc::clone(&metrics),
        );

        Ok(Self {
            client: Some(client),
            runtime: Some(runtime),
            acquire_gate,
            metrics,
            active_async_requests: AsyncRequestRegistry::default(),
            max_response_body_size,
            buffered_body_budget,
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
        body_replayable: bool,
        pool_timeout: f64,
        total_timeout: f64,
    ) -> PyResult<RawResponse> {
        validate_request_timeouts(pool_timeout, total_timeout)?;

        let client = self.client()?.clone();
        let runtime = self.runtime()?;
        let acquire_gate = self.acquire_gate.clone();
        let metrics = Arc::clone(&self.metrics);
        let max_response_body_size = self.max_response_body_size;
        let buffered_body_budget = self.buffered_body_budget.clone();
        let follow_redirects = self.follow_redirects;
        let max_redirects = self.max_redirects;
        self.metrics.request_started();

        let result = py.detach(|| {
            runtime.block_on(async move {
                send_request(
                    client,
                    acquire_gate,
                    metrics,
                    pool_timeout,
                    TransportRequest {
                        method,
                        url,
                        headers,
                        body,
                        body_replayable,
                        total_timeout,
                        max_response_body_size,
                        buffered_body_budget,
                        follow_redirects,
                        max_redirects,
                    },
                )
                .await
            })
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
        body_replayable: bool,
        pool_timeout: f64,
        total_timeout: f64,
    ) -> PyResult<Py<PyAny>> {
        validate_request_timeouts(pool_timeout, total_timeout)?;

        let client = self.client()?.clone();
        let runtime = self.runtime()?;
        let max_response_body_size = self.max_response_body_size;
        let buffered_body_budget = self.buffered_body_budget.clone();
        let follow_redirects = self.follow_redirects;
        let max_redirects = self.max_redirects;
        spawn_async_request(
            py,
            runtime,
            &self.active_async_requests,
            AsyncRequestSpawn {
                acquire_gate: self.acquire_gate.clone(),
                client,
                metrics: Arc::clone(&self.metrics),
                pool_timeout,
                request: TransportRequest {
                    method,
                    url,
                    headers,
                    body,
                    body_replayable,
                    total_timeout,
                    max_response_body_size,
                    buffered_body_budget,
                    follow_redirects,
                    max_redirects,
                },
            },
        )
    }

    fn stats(&self) -> RawStats {
        self.metrics.snapshot().into()
    }

    fn transport_state(&self) -> RawTransportState {
        self.metrics.transport_state_snapshot().into()
    }

    fn pool_diagnostics(&self) -> RawPoolDiagnostics {
        self.acquire_gate.diagnostics().into()
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
        self.active_async_requests.abort_all();
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
