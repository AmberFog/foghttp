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
mod tests {
    use super::{build_request, RequestBodyParts, RequestParts};
    use hyper::header::{InvalidHeaderValue, PROXY_AUTHORIZATION};
    use hyper::http::{method::InvalidMethod, uri::InvalidUri};

    fn request_parts() -> RequestParts {
        RequestParts {
            method: "POST".to_owned(),
            url: "http://example.com/echo".to_owned(),
            headers: vec![("x-test".to_owned(), "value".to_owned())],
            body: RequestBodyParts::Buffered(Some(vec![1, 2, 3])),
            proxy_authorization: None,
        }
    }

    #[test]
    fn invalid_method_is_rejected_before_uri() {
        let mut parts = request_parts();
        parts.method = "NOT A METHOD".to_owned();
        parts.url = "http://[".to_owned();
        let error = build_request(parts, None).err().expect("invalid method");
        assert!(error.is::<InvalidMethod>());
        assert_eq!(error.to_string(), error.get_ref().to_string());
    }

    #[test]
    fn invalid_uri_retains_parse_error() {
        let mut parts = request_parts();
        parts.url = "http://[".to_owned();
        let error = build_request(parts, None).err().expect("invalid URI");
        assert!(error.is::<InvalidUri>());
        assert_eq!(error.to_string(), error.get_ref().to_string());
    }

    #[test]
    fn invalid_proxy_authorization_retains_header_error() {
        let mut parts = request_parts();
        parts.proxy_authorization = Some("bad\r\nvalue".to_owned());
        let error = build_request(parts, None)
            .err()
            .expect("invalid proxy header");
        assert!(error.is::<InvalidHeaderValue>());
    }

    #[test]
    fn valid_request_preserves_headers_body_and_completion() {
        use http_body_util::BodyExt;

        let mut parts = request_parts();
        parts.proxy_authorization = Some("Basic dGVzdA==".to_owned());
        let (request, completion) = build_request(parts, None).expect("valid request");
        assert_eq!(request.method(), "POST");
        assert_eq!(request.uri(), "http://example.com/echo");
        assert_eq!(request.headers()["x-test"], "value");
        assert_eq!(request.headers()[PROXY_AUTHORIZATION], "Basic dGVzdA==");
        assert!(!completion.is_complete());

        let runtime = tokio::runtime::Builder::new_current_thread()
            .build()
            .unwrap();
        let body = runtime.block_on(request.into_body().collect()).unwrap();
        assert_eq!(body.to_bytes().as_ref(), &[1, 2, 3]);
        assert!(!completion.is_complete());
        completion.mark_transport_flushed();
        assert!(completion.is_complete());
    }
}
