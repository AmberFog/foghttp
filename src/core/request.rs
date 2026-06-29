use crate::core::client::{
    buffered_request_body, streaming_request_body, RequestBody, UploadBodyReceiver,
};
use crate::core::headers::{request_headers, HeaderPairs};
use crate::errors::FogHttpError;
use hyper::header::{HeaderValue, PROXY_AUTHORIZATION};
use hyper::{Method, Request, Uri};
use pyo3::prelude::*;
use std::str::FromStr;

pub struct RequestParts {
    pub method: String,
    pub url: String,
    pub headers: HeaderPairs,
    pub body: RequestBodyParts,
    pub proxy_authorization: Option<String>,
}

pub enum RequestBodyParts {
    Buffered(Option<Vec<u8>>),
    Streaming {
        receiver: UploadBodyReceiver,
        content_length: Option<u64>,
    },
}

pub fn build_request(parts: RequestParts) -> PyResult<Request<RequestBody>> {
    let method = Method::from_bytes(parts.method.as_bytes())
        .map_err(|err| FogHttpError::new_err(err.to_string()))?;
    let uri = Uri::from_str(&parts.url).map_err(|err| FogHttpError::new_err(err.to_string()))?;
    let body = match parts.body {
        RequestBodyParts::Buffered(content) => buffered_request_body(content),
        RequestBodyParts::Streaming {
            receiver,
            content_length,
        } => streaming_request_body(receiver, content_length),
    };
    let mut request = Request::builder()
        .method(method)
        .uri(uri)
        .body(body)
        .map_err(|err| FogHttpError::new_err(err.to_string()))?;

    *request.headers_mut() = request_headers(parts.headers)?;
    if let Some(proxy_authorization) = parts.proxy_authorization {
        let value = HeaderValue::from_str(&proxy_authorization)
            .map_err(|err| FogHttpError::new_err(err.to_string()))?;
        request.headers_mut().insert(PROXY_AUTHORIZATION, value);
    }
    Ok(request)
}
