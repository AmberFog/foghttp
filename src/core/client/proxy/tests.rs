use super::HttpProxyConnector;
use hyper::rt::{Read, ReadBufCursor, Write};
use hyper::Uri;
use hyper_util::client::legacy::connect::{Connected, Connection};
use std::future::{ready, Ready};
use std::io::{Error, IoSlice};
use std::pin::Pin;
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll};
use tokio::runtime::{Builder, Runtime};
use tower_service::Service;

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
