pub(crate) mod acquire;
mod async_requests;
mod auth;
mod future;
mod lifecycle;
mod options;
mod policy_hooks;
mod process;
mod runtime;
mod streams;
mod timeout_diagnostics;
mod transport;
mod upload_body;

use crate::core::client::{
    build_client_with_connection_gate, build_write_timeout_client_with_connection_gate,
    ClientOptions, ConnectionGate,
};
use crate::core::headers::HeaderPairs;
use crate::core::metrics::Metrics;
use crate::core::policy::{CookieJar, RetryPolicy, SsrfPolicy};
use crate::core::response::BufferedBodyBudget;
use crate::errors::FogHttpError;
use crate::py::client::acquire::AcquireGate;
use crate::py::client::async_requests::{
    spawn_async_request, spawn_async_stream_request, AsyncRequestRegistry, AsyncRequestSpawn,
    AsyncStreamRequestSpawn, RequestCompletion,
};
use crate::py::client::auth::PythonAuth;
use crate::py::client::future::PythonFutureSetters;
use crate::py::client::options::{
    validate_numeric_client_options, validate_request_timeouts, NumericClientOptions,
};
use crate::py::client::policy_hooks::PythonPolicyHooks;
use crate::py::client::process::{client_used_after_fork, current_process_id, ProcessId};
use crate::py::client::runtime::{parse_runtime_mode, ClientRuntime};
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

pub use streams::RawStreamResponse;
pub use upload_body::RawUploadBody;

#[pyclass]
pub struct RawClient {
    clients: Option<TransportClients>,
    runtime: Option<ClientRuntime>,
    acquire_gate: AcquireGate,
    metrics: Arc<Metrics>,
    active_async_requests: AsyncRequestRegistry,
    active_streams: StreamRegistry,
    future_setters: PythonFutureSetters,
    max_response_body_size: Option<usize>,
    buffered_body_budget: BufferedBodyBudget,
    follow_redirects: bool,
    max_redirects: usize,
    cookie_jar: Option<CookieJar>,
    proxy_authorization: Option<String>,
    auth: Option<Arc<PythonAuth>>,
    policy_hooks: Option<Arc<PythonPolicyHooks>>,
    retry_policy: Option<RetryPolicy>,
    ssrf_policy: Option<Arc<SsrfPolicy>>,
    process_id: ProcessId,
}

#[pymethods]
impl RawClient {
    #[new]
    #[pyo3(signature = (
        *,
        max_active_requests,
        max_active_requests_per_origin,
        max_connections,
        max_connections_per_host,
        max_idle_connections_per_host,
        max_pending_requests,
        max_response_body_size,
        max_buffered_response_bytes,
        idle_timeout,
        keepalive,
        connect_timeout,
        follow_redirects,
        max_redirects,
        cookies_enabled,
        ca_certificates,
        trust_webpki_roots,
        runtime,
        runtime_workers,
        http_proxy_url,
        http_proxy_authorization,
        https_proxy_url,
        https_proxy_authorization,
        auth_basic_authorization,
        auth_hook,
        policy_hooks,
        retry_retries,
        retry_backoff,
        retry_jitter,
        retry_statuses,
        retry_methods,
        retry_network_errors,
        ssrf_allowed_schemes,
        ssrf_allowed_origins,
        ssrf_allowed_domains
    ))]
    #[allow(
        clippy::fn_params_excessive_bools,
        clippy::too_many_arguments,
        clippy::too_many_lines,
        clippy::similar_names,
        reason = "PyO3 constructor mirrors Python client options and resource construction."
    )]
    fn new(
        py: Python<'_>,
        max_active_requests: usize,
        max_active_requests_per_origin: Option<usize>,
        max_connections: Option<usize>,
        max_connections_per_host: Option<usize>,
        max_idle_connections_per_host: usize,
        max_pending_requests: usize,
        max_response_body_size: Option<usize>,
        max_buffered_response_bytes: Option<usize>,
        idle_timeout: f64,
        keepalive: bool,
        connect_timeout: f64,
        follow_redirects: bool,
        max_redirects: usize,
        cookies_enabled: bool,
        ca_certificates: Vec<Vec<u8>>,
        trust_webpki_roots: bool,
        runtime: &str,
        runtime_workers: Option<usize>,
        http_proxy_url: Option<String>,
        http_proxy_authorization: Option<String>,
        https_proxy_url: Option<String>,
        https_proxy_authorization: Option<String>,
        auth_basic_authorization: Option<String>,
        auth_hook: Option<Py<PyAny>>,
        policy_hooks: Option<Py<PyAny>>,
        retry_retries: Option<usize>,
        retry_backoff: f64,
        retry_jitter: f64,
        retry_statuses: Vec<u16>,
        retry_methods: Vec<String>,
        retry_network_errors: bool,
        ssrf_allowed_schemes: Option<Vec<String>>,
        ssrf_allowed_origins: Vec<String>,
        ssrf_allowed_domains: Vec<String>,
    ) -> PyResult<Self> {
        validate_numeric_client_options(NumericClientOptions {
            max_active_requests,
            max_active_requests_per_origin,
            max_connections,
            max_connections_per_host,
            max_idle_connections_per_host,
            max_pending_requests,
            max_response_body_size,
            max_buffered_response_bytes,
            idle_timeout,
            connect_timeout,
        })?;
        let auth = PythonAuth::from_config(py, auth_basic_authorization, auth_hook)?;
        let policy_hooks = PythonPolicyHooks::from_config(py, policy_hooks)?;
        let retry_policy = retry_retries
            .map(|retries| {
                RetryPolicy::new(
                    retries,
                    retry_backoff,
                    retry_jitter,
                    retry_statuses,
                    retry_methods,
                    retry_network_errors,
                )
            })
            .transpose()
            .map_err(FogHttpError::new_err)?;
        let ssrf_policy = match ssrf_allowed_schemes {
            Some(schemes) => Some(Arc::new(
                SsrfPolicy::new(schemes, ssrf_allowed_origins, ssrf_allowed_domains)
                    .map_err(FogHttpError::new_err)?,
            )),
            None if ssrf_allowed_origins.is_empty() && ssrf_allowed_domains.is_empty() => None,
            None => {
                return Err(FogHttpError::new_err(
                    "SSRF policy allowlists require allowed schemes",
                ));
            }
        };

        let runtime_mode = parse_runtime_mode(runtime)?;
        let metrics = Arc::new(Metrics::default());
        let connection_gate = ConnectionGate::new(max_connections, max_connections_per_host);
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
            ssrf_policy: ssrf_policy.clone(),
        };
        let client = build_client_with_connection_gate(
            &client_options,
            Arc::clone(&metrics),
            connection_gate.clone(),
        )
        .map_err(FogHttpError::new_err)?;
        let write_timeout_client = build_write_timeout_client_with_connection_gate(
            &client_options,
            Arc::clone(&metrics),
            connection_gate.clone(),
        )
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
            .map(|options| {
                build_client_with_connection_gate(
                    options,
                    Arc::clone(&metrics),
                    connection_gate.clone(),
                )
            })
            .transpose()
            .map_err(FogHttpError::new_err)?;
        let proxy_write_timeout_client = proxy_options
            .as_ref()
            .map(|options| {
                build_write_timeout_client_with_connection_gate(
                    options,
                    Arc::clone(&metrics),
                    connection_gate.clone(),
                )
            })
            .transpose()
            .map_err(FogHttpError::new_err)?;
        let buffered_body_budget =
            BufferedBodyBudget::new(max_buffered_response_bytes, Arc::clone(&metrics));
        let acquire_gate = AcquireGate::new(
            max_active_requests,
            max_active_requests_per_origin,
            max_pending_requests,
            Arc::clone(&metrics),
        );
        let runtime = ClientRuntime::build(py, max_active_requests, runtime_mode, runtime_workers)?;
        let future_setters = PythonFutureSetters::new(py)?;
        let cookie_jar = cookies_enabled.then(CookieJar::new);

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
            future_setters,
            max_response_body_size,
            buffered_body_budget,
            follow_redirects,
            max_redirects,
            cookie_jar,
            proxy_authorization: http_proxy_authorization,
            auth,
            policy_hooks,
            retry_policy,
            ssrf_policy,
            process_id: current_process_id(),
        })
    }

    #[pyo3(signature = (
        *,
        method,
        url,
        headers,
        auth_override_headers,
        auth_removed_headers,
        extensions=None,
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
        auth_override_headers: Option<Vec<String>>,
        auth_removed_headers: Vec<String>,
        extensions: Option<Py<PyAny>>,
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
        self.ensure_current_process()?;
        validate_request_timeouts(pool_timeout, read_timeout, write_timeout, total_timeout)?;

        let clients = self.clients_unchecked()?.clone();
        let runtime = self.runtime_unchecked()?;
        let acquire_gate = self.acquire_gate.clone();
        let metrics = Arc::clone(&self.metrics);
        let max_response_body_size = self.max_response_body_size;
        let buffered_body_budget = self.buffered_body_budget.clone();
        let follow_redirects = self.follow_redirects;
        let max_redirects = self.max_redirects;
        let cookie_jar = self.cookie_jar.clone();
        let proxy_authorization = self.proxy_authorization.clone();
        let extensions = self.retained_request_extensions(extensions);
        let auth = self.auth.clone();
        let policy_hooks = self.policy_hooks.clone();
        let retry_policy = self.retry_policy.clone();
        let ssrf_policy = self.ssrf_policy.clone();
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
                        auth_override_headers,
                        auth_removed_headers,
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
                        retry_policy,
                        ssrf_policy,
                        cookie_jar,
                        auth,
                        policy_hooks,
                        extensions,
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
        auth_override_headers,
        auth_removed_headers,
        extensions=None,
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
        auth_override_headers: Option<Vec<String>>,
        auth_removed_headers: Vec<String>,
        extensions: Option<Py<PyAny>>,
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
        self.ensure_current_process()?;
        validate_request_timeouts(pool_timeout, read_timeout, write_timeout, total_timeout)?;

        let clients = self.clients_unchecked()?.clone();
        let runtime = self.runtime_unchecked()?;
        let max_response_body_size = self.max_response_body_size;
        let buffered_body_budget = self.buffered_body_budget.clone();
        let follow_redirects = self.follow_redirects;
        let max_redirects = self.max_redirects;
        let cookie_jar = self.cookie_jar.clone();
        let proxy_authorization = self.proxy_authorization.clone();
        let extensions = self.retained_request_extensions(extensions);
        let auth = self.auth.clone();
        let policy_hooks = self.policy_hooks.clone();
        let retry_policy = self.retry_policy.clone();
        let ssrf_policy = self.ssrf_policy.clone();
        spawn_async_request(
            py,
            runtime,
            &self.active_async_requests,
            AsyncRequestSpawn {
                acquire_gate: self.acquire_gate.clone(),
                clients,
                metrics: Arc::clone(&self.metrics),
                pool_timeout,
                future_setters: self.future_setters.clone_ref(py),
                request: TransportRequest {
                    method,
                    url,
                    headers,
                    auth_override_headers,
                    auth_removed_headers,
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
                    retry_policy,
                    ssrf_policy,
                    cookie_jar,
                    auth,
                    policy_hooks,
                    extensions,
                },
            },
        )
    }

    #[pyo3(signature = (
        *,
        method,
        url,
        headers,
        auth_override_headers,
        auth_removed_headers,
        extensions=None,
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
        auth_override_headers: Option<Vec<String>>,
        auth_removed_headers: Vec<String>,
        extensions: Option<Py<PyAny>>,
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
        self.ensure_current_process()?;
        validate_request_timeouts(pool_timeout, read_timeout, write_timeout, total_timeout)?;

        let clients = self.clients_unchecked()?.clone();
        let runtime = self.runtime_unchecked()?;
        let acquire_gate = self.acquire_gate.clone();
        let metrics = Arc::clone(&self.metrics);
        let active_streams = self.active_streams.clone();
        let runtime_handle = runtime.handle().clone();
        let max_response_body_size = self.max_response_body_size;
        let buffered_body_budget = self.buffered_body_budget.clone();
        let follow_redirects = self.follow_redirects;
        let max_redirects = self.max_redirects;
        let cookie_jar = self.cookie_jar.clone();
        let proxy_authorization = self.proxy_authorization.clone();
        let extensions = self.retained_request_extensions(extensions);
        let auth = self.auth.clone();
        let policy_hooks = self.policy_hooks.clone();
        let retry_policy = self.retry_policy.clone();
        let ssrf_policy = self.ssrf_policy.clone();
        let completion = RequestCompletion::default();
        let request_completion = completion.clone();
        let future_setters = self.future_setters.clone_ref(py);
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
                    future_setters,
                    TransportRequest {
                        method,
                        url,
                        headers,
                        auth_override_headers,
                        auth_removed_headers,
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
                        retry_policy,
                        ssrf_policy,
                        cookie_jar,
                        auth,
                        policy_hooks,
                        extensions,
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
        auth_override_headers,
        auth_removed_headers,
        extensions=None,
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
        auth_override_headers: Option<Vec<String>>,
        auth_removed_headers: Vec<String>,
        extensions: Option<Py<PyAny>>,
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
        self.ensure_current_process()?;
        validate_request_timeouts(pool_timeout, read_timeout, write_timeout, total_timeout)?;

        let clients = self.clients_unchecked()?.clone();
        let runtime = self.runtime_unchecked()?;
        let max_response_body_size = self.max_response_body_size;
        let buffered_body_budget = self.buffered_body_budget.clone();
        let follow_redirects = self.follow_redirects;
        let max_redirects = self.max_redirects;
        let cookie_jar = self.cookie_jar.clone();
        let proxy_authorization = self.proxy_authorization.clone();
        let extensions = self.retained_request_extensions(extensions);
        let auth = self.auth.clone();
        let policy_hooks = self.policy_hooks.clone();
        let retry_policy = self.retry_policy.clone();
        let ssrf_policy = self.ssrf_policy.clone();
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
                future_setters: self.future_setters.clone_ref(py),
                request: TransportRequest {
                    method,
                    url,
                    headers,
                    auth_override_headers,
                    auth_removed_headers,
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
                    retry_policy,
                    ssrf_policy,
                    cookie_jar,
                    auth,
                    policy_hooks,
                    extensions,
                },
            },
        )
    }

    fn stats(&self) -> PyResult<RawStats> {
        self.ensure_current_process()?;
        Ok(self.metrics.stats_snapshot().into())
    }

    fn transport_state(&self) -> PyResult<RawTransportState> {
        self.ensure_current_process()?;
        Ok(self.metrics.transport_state_snapshot().into())
    }

    fn pool_diagnostics(&self) -> PyResult<RawPoolDiagnostics> {
        self.ensure_current_process()?;
        Ok(self.acquire_gate.diagnostics().into())
    }

    fn close(&mut self) {
        self.close_resources();
    }
}

impl RawClient {
    fn retained_request_extensions(&self, extensions: Option<Py<PyAny>>) -> Option<Py<PyAny>> {
        extensions.filter(|_| {
            self.policy_hooks.is_some() || self.auth.as_ref().is_some_and(|auth| auth.uses_hook())
        })
    }

    fn clients_unchecked(&self) -> PyResult<&TransportClients> {
        self.clients
            .as_ref()
            .ok_or_else(|| FogHttpError::new_err("client is closed"))
    }

    fn runtime_unchecked(&self) -> PyResult<&tokio::runtime::Runtime> {
        self.runtime
            .as_ref()
            .map(ClientRuntime::runtime)
            .ok_or_else(|| FogHttpError::new_err("client runtime is closed"))
    }

    fn ensure_current_process(&self) -> PyResult<()> {
        let current_process_id = current_process_id();
        if self.process_id == current_process_id {
            return Ok(());
        }
        Err(client_used_after_fork(self.process_id, current_process_id))
    }

    fn close_resources(&mut self) {
        self.cookie_jar.take();
        let current_process = self.process_id == current_process_id();
        if current_process {
            self.active_async_requests.abort_all();
            self.active_streams.abort_all();
            self.clients.take();
            if let Some(runtime) = self.runtime.take() {
                runtime.shutdown_background();
            }
            return;
        }

        // Inherited transport state can reference threads that vanished at fork.
        // The child copy is reclaimed by the OS when the child exits.
        std::mem::forget(self.clients.take());
        if let Some(runtime) = self.runtime.take() {
            runtime.abandon_without_shutdown();
        }
        std::mem::forget(std::mem::take(&mut self.active_async_requests));
        std::mem::forget(std::mem::take(&mut self.active_streams));
    }
}

impl Drop for RawClient {
    fn drop(&mut self) {
        self.close_resources();
    }
}
