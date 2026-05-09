use crate::core::client::RequestBody;
use crate::core::headers::{request_headers, HeaderPairs};
use crate::errors::FogHttpError;
use bytes::Bytes;
use http_body_util::Full;
use hyper::{Method, Request, Uri};
use pyo3::prelude::*;
use std::str::FromStr;

pub struct RequestParts {
    pub method: String,
    pub url: String,
    pub headers: HeaderPairs,
    pub body: Option<Vec<u8>>,
}

pub fn build_request(parts: RequestParts) -> PyResult<Request<RequestBody>> {
    let method = Method::from_bytes(parts.method.as_bytes())
        .map_err(|err| FogHttpError::new_err(err.to_string()))?;
    let uri = Uri::from_str(&parts.url).map_err(|err| FogHttpError::new_err(err.to_string()))?;
    let mut request = Request::builder()
        .method(method)
        .uri(uri)
        .body(Full::new(Bytes::from(parts.body.unwrap_or_default())))
        .map_err(|err| FogHttpError::new_err(err.to_string()))?;

    *request.headers_mut() = request_headers(parts.headers)?;
    Ok(request)
}
