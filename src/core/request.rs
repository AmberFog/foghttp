use crate::core::client::{
    buffered_request_body, streaming_request_body, RequestBody, RequestBodyCompletion,
    RequestWriteTimeoutContext, UploadBodyReceiver,
};
use crate::core::headers::{request_headers, HeaderPairs};
use hyper::header::{HeaderValue, PROXY_AUTHORIZATION};
use hyper::http::Error;
use hyper::{Method, Request, Uri};
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

pub fn build_request(
    parts: RequestParts,
    write_timeout: Option<RequestWriteTimeoutContext>,
) -> Result<(Request<RequestBody>, RequestBodyCompletion), Error> {
    let method = Method::from_bytes(parts.method.as_bytes())?;
    let uri = Uri::from_str(&parts.url)?;
    let (body, body_completion) = match parts.body {
        RequestBodyParts::Buffered(content) => buffered_request_body(content),
        RequestBodyParts::Streaming {
            receiver,
            content_length,
        } => streaming_request_body(receiver, content_length, write_timeout),
    };
    let mut request = Request::builder().method(method).uri(uri).body(body)?;

    *request.headers_mut() = request_headers(parts.headers)?;
    if let Some(proxy_authorization) = parts.proxy_authorization {
        let value = HeaderValue::from_str(&proxy_authorization)?;
        request.headers_mut().insert(PROXY_AUTHORIZATION, value);
    }
    Ok((request, body_completion))
}

#[cfg(test)]
mod tests;
