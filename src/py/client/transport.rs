use crate::core::client::HyperClient;
use crate::core::headers::response_headers;
use crate::core::request::{build_request, RequestParts};
use crate::core::response::collect_body;
use crate::errors::{FogHttpError, FogHttpTimeoutError};
use crate::messages::REQUEST_TOTAL_TIMEOUT;
use crate::py::response::RawResponse;
use pyo3::prelude::*;
use std::collections::HashMap;
use std::time::{Duration, Instant};

pub async fn send_request(
    client: HyperClient,
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
        client.request(request),
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
