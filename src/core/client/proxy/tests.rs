use super::{
    establish_tunnel, find_headers_end, parse_connect_status, tunnel_authority, HttpProxyConnector,
    ProxyAuthorization,
};
use crate::messages::PROXY_CONNECT_CLOSED;
use hyper::rt::{Read, ReadBufCursor, Write};
use hyper::Uri;
use hyper_util::client::legacy::connect::{Connected, Connection};
use hyper_util::rt::TokioIo;
use std::future::{ready, Ready};
use std::io::{Error, IoSlice};
use std::pin::Pin;
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::runtime::{Builder, Runtime};
use tower_service::Service;

#[test]
fn tunnel_authority_uses_default_https_port_when_absent() {
    assert_eq!(
        tunnel_authority(&http_uri("https://api.example/items")).unwrap(),
        "api.example:443",
    );
    assert_eq!(
        tunnel_authority(&http_uri("https://api.example:8443/items")).unwrap(),
        "api.example:8443",
    );
}

#[test]
fn tunnel_authority_preserves_bracketed_ipv6_host() {
    assert_eq!(
        tunnel_authority(&http_uri("https://[::1]:8443/items")).unwrap(),
        "[::1]:8443",
    );
}

#[test]
fn find_headers_end_detects_terminator() {
    assert_eq!(find_headers_end(b"HTTP/1.1 200 OK\r\n\r\n"), Some(19));
    assert_eq!(find_headers_end(b"HTTP/1.1 200 OK\r\n"), None);
}

#[test]
fn parse_connect_status_reads_status_code() {
    assert_eq!(
        parse_connect_status(b"HTTP/1.1 200 Connection Established\r\n\r\n").unwrap(),
        200,
    );
    assert_eq!(
        parse_connect_status(b"HTTP/1.1   200   Connection Established\r\n\r\n").unwrap(),
        200,
    );
    assert_eq!(
        parse_connect_status(b"HTTP/1.0 407 Proxy Authentication Required\r\n\r\n").unwrap(),
        407,
    );
    assert!(parse_connect_status(b"GARBAGE\r\n\r\n").is_err());
    assert!(parse_connect_status(b"HTTP/1.1 OK\r\n\r\n").is_err());
}

#[test]
fn proxy_authorization_rejects_invalid_header_value() {
    assert!(ProxyAuthorization::parse("Basic ok\r\nInjected: yes").is_err());
}

#[test]
fn establish_tunnel_sends_connect_and_returns_stream_on_success() {
    runtime().block_on(async {
        let (client, mut server) = tokio::io::duplex(1024);
        let proxy_authorization = ProxyAuthorization::parse("Basic c2VjcmV0").unwrap();
        server
            .write_all(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            .await
            .unwrap();

        let tunnel = establish_tunnel(
            TokioIo::new(client),
            "api.example:443",
            Some(&proxy_authorization),
        )
        .await;
        assert!(tunnel.is_ok());

        let mut request = vec![0_u8; 1024];
        let read = server.read(&mut request).await.unwrap();
        let request = String::from_utf8_lossy(&request[..read]);
        assert!(request.starts_with("CONNECT api.example:443 HTTP/1.1\r\n"));
        assert!(request.contains("Host: api.example:443\r\n"));
        assert!(request.contains("Proxy-Authorization: Basic c2VjcmV0\r\n"));
    });
}

#[test]
fn establish_tunnel_rejects_non_2xx_status() {
    runtime().block_on(async {
        let (client, mut server) = tokio::io::duplex(1024);
        server
            .write_all(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")
            .await
            .unwrap();

        let Err(error) = establish_tunnel(TokioIo::new(client), "api.example:443", None).await
        else {
            panic!("non-2xx CONNECT must fail");
        };
        assert!(error.to_string().contains("407"));
    });
}

#[test]
fn establish_tunnel_rejects_non_2xx_status_with_body_using_status() {
    runtime().block_on(async {
        let (client, mut server) = tokio::io::duplex(1024);
        server
            .write_all(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 11\r\n\r\nproxy error")
            .await
            .unwrap();

        let Err(error) = establish_tunnel(TokioIo::new(client), "api.example:443", None).await
        else {
            panic!("non-2xx CONNECT with body must surface status");
        };
        assert!(error.to_string().contains("502"));
    });
}

#[test]
fn establish_tunnel_preserves_2xx_response_extra_bytes_as_tunnel_data() {
    runtime().block_on(async {
        let (client, mut server) = tokio::io::duplex(1024);
        server
            .write_all(b"HTTP/1.1 200 Connection Established\r\n\r\ntunnel-data")
            .await
            .unwrap();

        let tunnel = establish_tunnel(TokioIo::new(client), "api.example:443", None)
            .await
            .expect("successful CONNECT should preserve bytes after headers as tunnel data");
        let mut tunnel = TokioIo::new(tunnel);
        let mut payload = [0_u8; 11];

        tunnel.read_exact(&mut payload).await.unwrap();

        assert_eq!(&payload, b"tunnel-data");
    });
}

#[test]
fn establish_tunnel_errors_when_proxy_closes_before_response() {
    runtime().block_on(async {
        let (client, mut server) = tokio::io::duplex(1024);
        let server_task = tokio::spawn(async move {
            let mut request = [0_u8; 1024];
            let _ = server.read(&mut request).await;
            drop(server);
        });

        let Err(error) = establish_tunnel(TokioIo::new(client), "api.example:443", None).await
        else {
            panic!("closed tunnel must fail");
        };
        assert!(error.to_string().contains(PROXY_CONNECT_CLOSED));
        server_task.await.unwrap();
    });
}

#[test]
fn direct_connector_uses_target_uri_without_proxy_flag() {
    let calls = Arc::new(Mutex::new(Vec::new()));
    let target_uri = http_uri("http://api.example/items");
    let mut connector = HttpProxyConnector::direct(RecordingConnector::new(Arc::clone(&calls)));

    let connection = runtime()
        .block_on(connector.call(target_uri.clone()))
        .unwrap();

    assert!(!connection.connected().is_proxied());
    assert_eq!(recorded_calls(&calls), vec![target_uri]);
}

#[test]
fn http_proxy_connector_uses_proxy_uri_and_proxy_flag_for_http_targets() {
    let calls = Arc::new(Mutex::new(Vec::new()));
    let proxy_uri = http_uri("http://proxy.example:8080");
    let mut connector = HttpProxyConnector::http_proxy(
        RecordingConnector::new(Arc::clone(&calls)),
        proxy_uri.clone(),
    );

    let connection = runtime()
        .block_on(connector.call(http_uri("http://api.example/items")))
        .unwrap();

    assert!(connection.connected().is_proxied());
    assert_eq!(recorded_calls(&calls), vec![proxy_uri]);
}

#[test]
fn http_proxy_connector_does_not_proxy_https_targets() {
    let calls = Arc::new(Mutex::new(Vec::new()));
    let target_uri = http_uri("https://api.example/items");
    let proxy_uri = http_uri("http://proxy.example:8080");
    let mut connector =
        HttpProxyConnector::http_proxy(RecordingConnector::new(Arc::clone(&calls)), proxy_uri);

    let connection = runtime()
        .block_on(connector.call(target_uri.clone()))
        .unwrap();

    assert!(!connection.connected().is_proxied());
    assert_eq!(recorded_calls(&calls), vec![target_uri]);
}

#[derive(Clone)]
struct RecordingConnector {
    calls: Arc<Mutex<Vec<Uri>>>,
}

impl RecordingConnector {
    fn new(calls: Arc<Mutex<Vec<Uri>>>) -> Self {
        Self { calls }
    }
}

impl Service<Uri> for RecordingConnector {
    type Response = FakeConnection;
    type Error = String;
    type Future = Ready<Result<Self::Response, Self::Error>>;

    fn poll_ready(&mut self, _context: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        Poll::Ready(Ok(()))
    }

    fn call(&mut self, uri: Uri) -> Self::Future {
        self.calls.lock().unwrap().push(uri);
        ready(Ok(FakeConnection))
    }
}

struct FakeConnection;

impl Connection for FakeConnection {
    fn connected(&self) -> Connected {
        Connected::new()
    }
}

impl Read for FakeConnection {
    fn poll_read(
        self: Pin<&mut Self>,
        _context: &mut Context<'_>,
        _buffer: ReadBufCursor<'_>,
    ) -> Poll<Result<(), Error>> {
        Poll::Ready(Ok(()))
    }
}

impl Write for FakeConnection {
    fn poll_write(
        self: Pin<&mut Self>,
        _context: &mut Context<'_>,
        _buffer: &[u8],
    ) -> Poll<Result<usize, Error>> {
        Poll::Ready(Ok(0))
    }

    fn poll_flush(self: Pin<&mut Self>, _context: &mut Context<'_>) -> Poll<Result<(), Error>> {
        Poll::Ready(Ok(()))
    }

    fn poll_shutdown(self: Pin<&mut Self>, _context: &mut Context<'_>) -> Poll<Result<(), Error>> {
        Poll::Ready(Ok(()))
    }

    fn is_write_vectored(&self) -> bool {
        false
    }

    fn poll_write_vectored(
        self: Pin<&mut Self>,
        _context: &mut Context<'_>,
        _buffers: &[IoSlice<'_>],
    ) -> Poll<Result<usize, Error>> {
        Poll::Ready(Ok(0))
    }
}

fn runtime() -> Runtime {
    Builder::new_current_thread().build().unwrap()
}

fn http_uri(value: &str) -> Uri {
    value.parse().unwrap()
}

fn recorded_calls(calls: &Arc<Mutex<Vec<Uri>>>) -> Vec<Uri> {
    calls.lock().unwrap().clone()
}
