use crate::core::client::{build_client, ClientOptions, HyperClient};
use crate::core::headers::response_headers;
use crate::core::metrics::Metrics;
use crate::core::request::{build_request, RequestParts};
use crate::core::response::collect_body;
use crate::errors::{FogHttpError, FogHttpTimeoutError};
use crate::messages::{REDIRECTS_UNSUPPORTED, REQUEST_TOTAL_TIMEOUT, TRUST_ENV_UNSUPPORTED};
use crate::py::response::RawResponse;
use crate::py::stats::RawStats;
use pyo3::prelude::*;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::runtime::{Builder, Runtime};

#[pyclass]
pub struct RawClient {
    client: HyperClient,
    runtime: Runtime,
    metrics: Arc<Metrics>,
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
        trust_env: bool,
    ) -> PyResult<Self> {
        validate_unsupported_options(follow_redirects, trust_env)?;

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
            self.runtime
                .block_on(self.send_request(method, url, headers, body, total_timeout))
        });

        self.metrics.request_finished(result.is_err());
        result
    }

    fn stats(&self) -> RawStats {
        self.metrics.snapshot().into()
    }
}

impl RawClient {
    async fn send_request(
        &self,
        method: String,
        url: String,
        headers: HashMap<String, String>,
        body: Option<Vec<u8>>,
        total_timeout: f64,
    ) -> PyResult<RawResponse> {
        let started = Instant::now();
        let request = build_request(RequestParts {
            method,
            url: url.clone(),
            headers,
            body,
        })?;

        let response = tokio::time::timeout(
            Duration::from_secs_f64(total_timeout.max(0.0)),
            self.client.request(request),
        )
        .await
        .map_err(|_| FogHttpTimeoutError::new_err(REQUEST_TOTAL_TIMEOUT))?
        .map_err(|err| FogHttpError::new_err(err.to_string()))?;

        let status_code = response.status().as_u16();
        let http_version = format!("{:?}", response.version());
        let headers = response_headers(response.headers());
        let content = collect_body(response.into_body()).await?;

        Ok(RawResponse {
            status_code,
            headers,
            content,
            url,
            http_version,
            elapsed: started.elapsed().as_secs_f64(),
        })
    }
}

fn validate_unsupported_options(follow_redirects: bool, trust_env: bool) -> PyResult<()> {
    if follow_redirects {
        return Err(FogHttpError::new_err(REDIRECTS_UNSUPPORTED));
    }

    if trust_env {
        return Err(FogHttpError::new_err(TRUST_ENV_UNSUPPORTED));
    }

    Ok(())
}

fn build_runtime(max_connections: usize) -> PyResult<Runtime> {
    Builder::new_multi_thread()
        .worker_threads(max_connections.clamp(1, 32))
        .enable_all()
        .build()
        .map_err(|err| FogHttpError::new_err(err.to_string()))
}
