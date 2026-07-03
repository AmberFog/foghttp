pub(crate) mod acquire;
mod async_requests;
mod body;
mod future;
mod lifecycle;
mod options;
mod redirects;
mod runtime;
mod streams;
mod timeout_diagnostics;
mod transport;
mod upload_body;

use crate::core::client::{build_client, build_write_timeout_client, ClientOptions};
use crate::core::headers::HeaderPairs;
use crate::core::metrics::Metrics;
use crate::core::response::BufferedBodyBudget;
use crate::errors::FogHttpError;
use crate::py::client::acquire::AcquireGate;
use crate::py::client::async_requests::{
    spawn_async_request, spawn_async_stream_request, AsyncRequestRegistry, AsyncRequestSpawn,
    AsyncStreamRequestSpawn, RequestCompletion,
};
use crate::py::client::options::{
    validate_numeric_client_options, validate_request_timeouts, NumericClientOptions,
};
use crate::py::client::runtime::build_runtime;
use crate::py::client::streams::StreamRegistry;
use crate::py::client::transport::{
    send_request, send_stream_request, TransportClients, TransportRequest,
};
use crate::py::response::RawResponse;
use crate::py::stats::RawStats;
use crate::py::{RawPoolDiagnostics, RawTransportState};
use pyo3::prelude::*;
use pyo3::types::PyAny;
use std::sync::Arc;
use tokio::runtime::Runtime;

pub use streams::RawStreamResponse;
pub use upload_body::RawUploadBody;

#[pyclass]
pub struct RawClient {
    clients: Option<TransportClients>,
    runtime: Option<Runtime>,
    acquire_gate: AcquireGate,
    metrics: Arc<Metrics>,
    active_async_requests: AsyncRequestRegistry,
    active_streams: StreamRegistry,
    max_response_body_size: Option<usize>,
    buffered_body_budget: BufferedBodyBudget,
    follow_redirects: bool,
    max_redirects: usize,
    proxy_authorization: Option<String>,
}

#[pymethods]
impl RawClient {
    #[new]
    #[pyo3(signature = (
        *,
        max_active_requests,
        max_active_requests_per_origin,
        max_idle_connections_per_host,
        max_pending_requests,
        max_response_body_size,
        max_buffered_response_bytes,
        idle_timeout,
        keepalive,
        connect_timeout,
        follow_redirects,
        max_redirects,
        ca_certificates,
        trust_webpki_roots,
        runtime_workers,
        http_proxy_url,
        http_proxy_authorization,
        https_proxy_url,
        https_proxy_authorization
    ))]
    #[allow(
        clippy::fn_params_excessive_bools,
        clippy::too_many_arguments,
        clippy::similar_names,
        reason = "PyO3 constructor mirrors Python client options before transport grouping."
    )]
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
        runtime_workers: Option<usize>,
        http_proxy_url: Option<String>,
        http_proxy_authorization: Option<String>,
        https_proxy_url: Option<String>,
        https_proxy_authorization: Option<String>,
    ) -> PyResult<Self> {
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
            http_proxy_url: None,
            https_proxy_url: None,
            https_proxy_authorization: None,
        };
        let client =
            build_client(&client_options, Arc::clone(&metrics)).map_err(FogHttpError::new_err)?;
        let write_timeout_client =
            build_write_timeout_client(&client_options, Arc::clone(&metrics))
                .map_err(FogHttpError::new_err)?;
        let proxy_options = if http_proxy_url.is_some() || https_proxy_url.is_some() {
            Some(ClientOptions {
                http_proxy_url,
                https_proxy_url,
                https_proxy_authorization,
                ..client_options.clone()
            })
        } else {
            None
        };
        let proxy_client = proxy_options
            .as_ref()
            .map(|options| build_client(options, Arc::clone(&metrics)))
            .transpose()
            .map_err(FogHttpError::new_err)?;
        let proxy_write_timeout_client = proxy_options
            .as_ref()
            .map(|options| build_write_timeout_client(options, Arc::clone(&metrics)))
            .transpose()
            .map_err(FogHttpError::new_err)?;
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
            clients: Some(TransportClients::new(
                client,
                write_timeout_client,
                proxy_client,
                proxy_write_timeout_client,
            )),
            runtime: Some(runtime),
            acquire_gate,
            metrics,
            active_async_requests: AsyncRequestRegistry::default(),
            active_streams: StreamRegistry::default(),
            max_response_body_size,
            buffered_body_budget,
            follow_redirects,
            max_redirects,
            proxy_authorization: http_proxy_authorization,
        })
    }

    #[pyo3(signature = (
        *,
        method,
        url,
        headers,
        body,
        body_stream,
        body_replayable,
        use_proxy_transport,
        proxy_policy,
        pool_timeout,
        read_timeout,
        write_timeout,
        total_timeout
    ))]
    #[allow(clippy::too_many_arguments)]
    fn request(
        &self,
        py: Python<'_>,
        method: String,
        url: String,
        headers: HeaderPairs,
        body: Option<Vec<u8>>,
        body_stream: Option<Py<RawUploadBody>>,
        body_replayable: bool,
        use_proxy_transport: bool,
        proxy_policy: String,
        pool_timeout: f64,
        read_timeout: f64,
        write_timeout: f64,
        total_timeout: f64,
    ) -> PyResult<RawResponse> {
        validate_request_timeouts(pool_timeout, read_timeout, write_timeout, total_timeout)?;

        let clients = self.clients()?.clone();
        let runtime = self.runtime()?;
        let acquire_gate = self.acquire_gate.clone();
        let metrics = Arc::clone(&self.metrics);
        let max_response_body_size = self.max_response_body_size;
        let buffered_body_budget = self.buffered_body_budget.clone();
        let follow_redirects = self.follow_redirects;
        let max_redirects = self.max_redirects;
        let proxy_authorization = self.proxy_authorization.clone();
        self.metrics.request_started();

        let result = py.detach(|| {
            runtime.block_on(async move {
                send_request(
                    clients,
                    acquire_gate,
                    metrics,
                    pool_timeout,
                    TransportRequest {
                        method,
                        url,
                        headers,
                        body,
                        body_stream,
                        body_replayable,
                        use_proxy_transport,
                        proxy_policy,
                        proxy_authorization,
                        total_timeout,
                        read_timeout,
                        write_timeout,
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

    #[pyo3(signature = (
        *,
        method,
        url,
        headers,
        body,
        body_stream,
        body_replayable,
        use_proxy_transport,
        proxy_policy,
        pool_timeout,
        read_timeout,
        write_timeout,
        total_timeout
    ))]
    #[allow(clippy::too_many_arguments)]
    fn request_async(
        &self,
        py: Python<'_>,
        method: String,
        url: String,
        headers: HeaderPairs,
        body: Option<Vec<u8>>,
        body_stream: Option<Py<RawUploadBody>>,
        body_replayable: bool,
        use_proxy_transport: bool,
        proxy_policy: String,
        pool_timeout: f64,
        read_timeout: f64,
        write_timeout: f64,
        total_timeout: f64,
    ) -> PyResult<Py<PyAny>> {
        validate_request_timeouts(pool_timeout, read_timeout, write_timeout, total_timeout)?;

        let clients = self.clients()?.clone();
        let runtime = self.runtime()?;
        let max_response_body_size = self.max_response_body_size;
        let buffered_body_budget = self.buffered_body_budget.clone();
        let follow_redirects = self.follow_redirects;
        let max_redirects = self.max_redirects;
        let proxy_authorization = self.proxy_authorization.clone();
        spawn_async_request(
            py,
            runtime,
            &self.active_async_requests,
            AsyncRequestSpawn {
                acquire_gate: self.acquire_gate.clone(),
                clients,
                metrics: Arc::clone(&self.metrics),
                pool_timeout,
                request: TransportRequest {
                    method,
                    url,
                    headers,
                    body,
                    body_stream,
                    body_replayable,
                    use_proxy_transport,
                    proxy_policy,
                    proxy_authorization,
                    total_timeout,
                    read_timeout,
                    write_timeout,
                    max_response_body_size,
                    buffered_body_budget,
                    follow_redirects,
                    max_redirects,
                },
            },
        )
    }

    #[pyo3(signature = (
        *,
        method,
        url,
        headers,
        body,
        body_stream,
        body_replayable,
        use_proxy_transport,
        proxy_policy,
        pool_timeout,
        read_timeout,
        write_timeout,
        total_timeout
    ))]
    #[allow(clippy::too_many_arguments)]
    fn request_stream(
        &self,
        py: Python<'_>,
        method: String,
        url: String,
        headers: HeaderPairs,
        body: Option<Vec<u8>>,
        body_stream: Option<Py<RawUploadBody>>,
        body_replayable: bool,
        use_proxy_transport: bool,
        proxy_policy: String,
        pool_timeout: f64,
        read_timeout: f64,
        write_timeout: f64,
        total_timeout: f64,
    ) -> PyResult<RawStreamResponse> {
        validate_request_timeouts(pool_timeout, read_timeout, write_timeout, total_timeout)?;

        let clients = self.clients()?.clone();
        let runtime = self.runtime()?;
        let acquire_gate = self.acquire_gate.clone();
        let metrics = Arc::clone(&self.metrics);
        let active_streams = self.active_streams.clone();
        let runtime_handle = runtime.handle().clone();
        let max_response_body_size = self.max_response_body_size;
        let buffered_body_budget = self.buffered_body_budget.clone();
        let follow_redirects = self.follow_redirects;
        let max_redirects = self.max_redirects;
        let proxy_authorization = self.proxy_authorization.clone();
        let completion = RequestCompletion::default();
        let request_completion = completion.clone();
        self.metrics.request_started();

        let result = py.detach(|| {
            runtime.block_on(async move {
                send_stream_request(
                    clients,
                    acquire_gate,
                    Arc::clone(&metrics),
                    active_streams,
                    runtime_handle,
                    pool_timeout,
                    TransportRequest {
                        method,
                        url,
                        headers,
                        body,
                        body_stream,
                        body_replayable,
                        use_proxy_transport,
                        proxy_policy,
                        proxy_authorization,
                        total_timeout,
                        read_timeout,
                        write_timeout,
                        max_response_body_size,
                        buffered_body_budget,
                        follow_redirects,
                        max_redirects,
                    },
                    request_completion,
                )
                .await
            })
        });

        if result.is_err() && completion.finish() {
            self.metrics.request_finished(true);
        }
        result
    }

    #[pyo3(signature = (
        *,
        method,
        url,
        headers,
        body,
        body_stream,
        body_replayable,
        use_proxy_transport,
        proxy_policy,
        pool_timeout,
        read_timeout,
        write_timeout,
        total_timeout
    ))]
    #[allow(clippy::too_many_arguments)]
    fn request_stream_async(
        &self,
        py: Python<'_>,
        method: String,
        url: String,
        headers: HeaderPairs,
        body: Option<Vec<u8>>,
        body_stream: Option<Py<RawUploadBody>>,
        body_replayable: bool,
        use_proxy_transport: bool,
        proxy_policy: String,
        pool_timeout: f64,
        read_timeout: f64,
        write_timeout: f64,
        total_timeout: f64,
    ) -> PyResult<Py<PyAny>> {
        validate_request_timeouts(pool_timeout, read_timeout, write_timeout, total_timeout)?;

        let clients = self.clients()?.clone();
        let runtime = self.runtime()?;
        let max_response_body_size = self.max_response_body_size;
        let buffered_body_budget = self.buffered_body_budget.clone();
        let follow_redirects = self.follow_redirects;
        let max_redirects = self.max_redirects;
        let proxy_authorization = self.proxy_authorization.clone();
        spawn_async_stream_request(
            py,
            runtime,
            &self.active_async_requests,
            AsyncStreamRequestSpawn {
                acquire_gate: self.acquire_gate.clone(),
                clients,
                metrics: Arc::clone(&self.metrics),
                active_streams: self.active_streams.clone(),
                pool_timeout,
                request: TransportRequest {
                    method,
                    url,
                    headers,
                    body,
                    body_stream,
                    body_replayable,
                    use_proxy_transport,
                    proxy_policy,
                    proxy_authorization,
                    total_timeout,
                    read_timeout,
                    write_timeout,
                    max_response_body_size,
                    buffered_body_budget,
                    follow_redirects,
                    max_redirects,
                },
            },
        )
    }

    fn stats(&self) -> RawStats {
        self.metrics.stats_snapshot().into()
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
    fn clients(&self) -> PyResult<&TransportClients> {
        self.clients
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
        self.active_streams.abort_all();
        self.clients.take();
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
