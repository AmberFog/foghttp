use crate::core::client::HyperClient;
use crate::core::headers::response_headers;
use crate::core::request::{build_request, RequestParts};
use crate::core::response::collect_body;
use crate::errors::{FogHttpError, FogHttpTimeoutError};
use crate::messages::{redirect_limit_exceeded, REQUEST_TOTAL_TIMEOUT};
use crate::py::response::RawResponse;
use hyper::body::Incoming;
use hyper::{Response, StatusCode};
use pyo3::prelude::*;
use std::collections::HashMap;
use std::time::{Duration, Instant};

const REDIRECT_METHODS: [&str; 2] = ["GET", "HEAD"];

pub struct TransportRequest {
    pub method: String,
    pub url: String,
    pub headers: HashMap<String, String>,
    pub body: Option<Vec<u8>>,
    pub total_timeout: f64,
    pub follow_redirects: bool,
    pub max_redirects: usize,
}

pub async fn send_request(client: HyperClient, parts: TransportRequest) -> PyResult<RawResponse> {
    let started = Instant::now();
    let method = parts.method.to_uppercase();
    let mut request_url = parts.url;
    let mut history = Vec::new();

    loop {
        let request = build_request(RequestParts {
            method: method.clone(),
            url: request_url.clone(),
            headers: parts.headers.clone(),
            body: parts.body.clone(),
        })?;

        let response = tokio::time::timeout(
            remaining_duration(parts.total_timeout, started),
            client.request(request),
        )
        .await
        .map_err(|_| FogHttpTimeoutError::new_err(REQUEST_TOTAL_TIMEOUT))?
        .map_err(|err| FogHttpError::new_err(err.to_string()))?;

        let response_url = request_url.clone();
        let mut raw = raw_response(response, response_url.clone(), started).await?;
        let next_url = if parts.follow_redirects {
            redirect_target(&method, &response_url, raw.status_code, &raw.headers)
        } else {
            None
        };

        let Some(next_url) = next_url else {
            raw.history = history;
            return Ok(raw);
        };
        if history.len() >= parts.max_redirects {
            return Err(FogHttpError::new_err(redirect_limit_exceeded(
                parts.max_redirects,
                &response_url,
            )));
        }

        history.push(raw);
        request_url = next_url;
    }
}

async fn raw_response(
    response: Response<Incoming>,
    url: String,
    started: Instant,
) -> PyResult<RawResponse> {
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
        history: Vec::new(),
    })
}

fn remaining_duration(total_timeout: f64, started: Instant) -> Duration {
    Duration::from_secs_f64(total_timeout.max(0.0)).saturating_sub(started.elapsed())
}

fn redirect_target(
    method: &str,
    url: &str,
    status_code: u16,
    headers: &HashMap<String, String>,
) -> Option<String> {
    if !REDIRECT_METHODS.contains(&method) || !is_redirect_status(status_code) {
        return None;
    }

    let location = headers.get("location")?;
    Some(join_url(url, location))
}

fn is_redirect_status(status_code: u16) -> bool {
    let Ok(status_code) = StatusCode::from_u16(status_code) else {
        return false;
    };

    matches!(
        status_code,
        StatusCode::MOVED_PERMANENTLY
            | StatusCode::FOUND
            | StatusCode::SEE_OTHER
            | StatusCode::TEMPORARY_REDIRECT
            | StatusCode::PERMANENT_REDIRECT
    )
}

fn join_url(url: &str, location: &str) -> String {
    if location.starts_with("http://") || location.starts_with("https://") {
        return location.to_owned();
    }

    let Some(scheme_end) = url.find("://") else {
        return location.to_owned();
    };
    let origin_start = scheme_end + 3;
    let path_start = url[origin_start..]
        .find('/')
        .map_or(url.len(), |index| origin_start + index);
    let origin = &url[..path_start];

    if location.starts_with('/') {
        return format!("{origin}{location}");
    }

    let path = &url[path_start..];
    let directory_end = path
        .rfind('/')
        .map_or(path_start, |index| path_start + index + 1);
    format!("{}{}", &url[..directory_end], location)
}
