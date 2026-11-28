use super::{await_response_headers, captured_connection_guard, CapturedConnectionUse};
use crate::core::client::{
    buffered_request_body, streaming_request_body, upload_body_channel, ConnectionGate,
    ConnectionUseGuard, InstrumentedConnector, RequestBody, RequestBodyCompletion,
    RequestTaskContextExecutor,
};
use crate::core::metrics::{Metrics, ResponseBodyLifecycleOutcome};
use bytes::Bytes;
use http_body_util::BodyExt;
use hyper::body::Incoming;
use hyper::rt::{Read, ReadBufCursor, Write};
use hyper::{Request, Response, Uri};
use hyper_util::client::legacy::connect::{capture_connection, Connected, Connection};
use hyper_util::client::legacy::Client;
use hyper_util::rt::TokioIo;
use std::collections::VecDeque;
use std::future::{ready, Ready};
use std::io::{Error, ErrorKind};
use std::pin::Pin;
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll};
use std::time::Duration;
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader, DuplexStream};
use tokio::runtime::Builder;
use tokio::sync::oneshot;
use tower_service::Service;

const ORIGIN: &str = "http://upload.example.com";
const WATCHDOG: Duration = Duration::from_secs(2);
const IDLE_TIMEOUT: Duration = Duration::from_secs(30);
const EARLY_HEAD_AND_BODY: &[u8] =
    b"HTTP/1.1 413 Payload Too Large\r\ntransfer-encoding: chunked\r\n\r\n5\r\nearly\r\n";
const HEALTHY_RESPONSE: &[u8] = b"HTTP/1.1 200 OK\r\ncontent-length: 7\r\n\r\nhealthy";

type NativeClient = Client<InstrumentedConnector<DuplexConnector>, RequestBody>;

#[test]
fn early_response_poison_precedes_upload_abort_and_preserves_incoming_body() {
    runtime().block_on(async {
        tokio::time::timeout(WATCHDOG, async {
            let (first_client, first_server) = tokio::io::duplex(4_096);
            let metrics = Arc::new(Metrics::default());
            let mut connections = vec![first_client];
            let mut recovery_servers = Vec::new();
            let mut recovery_stops = Vec::new();
            for _ in 0..3 {
                let (client, server) = tokio::io::duplex(4_096);
                connections.push(client);
                let (stop, stopped) = oneshot::channel();
                recovery_stops.push(stop);
                recovery_servers.push(tokio::spawn(serve_healthy(server, 1, stopped)));
            }
            let client = client(connections, Arc::clone(&metrics));
            let (headers_sent, headers_received) = oneshot::channel();
            let (request_ended, request_end_received) = oneshot::channel();
            let (release_eof, eof_released) = oneshot::channel();
            let (stop_first, first_stopped) = oneshot::channel();
            let first_server = tokio::spawn(async move {
                let mut server = BufReader::new(first_server);
                let head = read_head(&mut server).await.unwrap();
                assert!(head.contains("transfer-encoding: chunked\r\n"));
                server
                    .get_mut()
                    .write_all(EARLY_HEAD_AND_BODY)
                    .await
                    .unwrap();
                headers_sent.send(()).unwrap();
                read_chunked_body(&mut server).await;
                request_ended.send(()).unwrap();
                eof_released.await.unwrap();
                server.get_mut().write_all(b"0\r\n\r\n").await.unwrap();
                let _stopped = first_stopped.await;
            });

            let (sender, receiver) = upload_body_channel(8);
            let (body, completion) = streaming_request_body(receiver, None, None);
            assert_eq!(
                sender.send_nowait(Ok(Bytes::from_static(b"upload"))),
                Ok(())
            );
            let (response, guard) = response_head(&client, "POST", body, completion.clone()).await;
            headers_received.await.unwrap();
            assert_eq!(response.status(), hyper::StatusCode::PAYLOAD_TOO_LARGE);
            assert!(!completion.is_complete());
            assert!(!sender.is_closed());

            sender.close();
            request_end_received.await.unwrap();
            assert!(!completion.is_complete());
            release_eof.send(()).unwrap();
            let content = response.into_body().collect().await.unwrap().to_bytes();
            assert_eq!(content, b"early".as_slice());

            // Retain the first response guard until recovery completes. The
            // physical limit permits recovery only after that socket closes.
            let (body, completion) = buffered_request_body(None);
            let (response, recovery_guard) = response_head(&client, "GET", body, completion).await;
            let content = response.into_body().collect().await.unwrap().to_bytes();
            assert_eq!(content, b"healthy".as_slice());
            recovery_guard.finish(ResponseBodyLifecycleOutcome::ReuseEligible);
            guard.finish(ResponseBodyLifecycleOutcome::ReuseEligible);
            let snapshot = metrics.snapshot();
            assert_eq!(snapshot.connections_opened, 2);
            assert_eq!(snapshot.connections_reused, 0);
            assert_eq!(snapshot.connections_aborted, 1);

            stop_first.send(()).unwrap();
            for stop in recovery_stops {
                let _stopped = stop.send(());
            }
            drop(client);
            first_server.await.unwrap();
            for server in recovery_servers {
                server.await.unwrap();
            }
        })
        .await
        .expect("early-response pool lifecycle did not finish before watchdog");
    });
}

#[test]
fn complete_upload_response_keeps_the_connection_poolable() {
    runtime().block_on(async {
        tokio::time::timeout(WATCHDOG, async {
            let (client_io, server_io) = tokio::io::duplex(4_096);
            let metrics = Arc::new(Metrics::default());
            let client = client(vec![client_io], Arc::clone(&metrics));
            let (stop, stopped) = oneshot::channel();
            let server = tokio::spawn(serve_healthy(server_io, 2, stopped));
            for _ in 0..2 {
                let (body, completion) = buffered_request_body(Some(b"complete".to_vec()));
                let completion_observer = completion.clone();
                let (response, guard) = response_head(&client, "POST", body, completion).await;
                assert!(completion_observer.is_complete());
                let content = response.into_body().collect().await.unwrap().to_bytes();
                assert_eq!(content, b"healthy".as_slice());
                guard.finish(ResponseBodyLifecycleOutcome::ReuseEligible);
            }
            let snapshot = metrics.snapshot();
            assert_eq!(snapshot.connections_opened, 1);
            assert_eq!(snapshot.connections_reused, 1);
            assert_eq!(snapshot.connections_aborted, 0);
            stop.send(()).unwrap();
            drop(client);
            server.await.unwrap();
        })
        .await
        .expect("complete-upload keepalive did not finish before watchdog");
    });
}

async fn response_head(
    client: &NativeClient,
    method: &str,
    body: RequestBody,
    completion: RequestBodyCompletion,
) -> (Response<Incoming>, ConnectionUseGuard) {
    let mut request = Request::builder()
        .method(method)
        .uri(ORIGIN)
        .body(body)
        .unwrap();
    let mut captured_connection = Some(CapturedConnectionUse::new(
        capture_connection(&mut request),
        None,
        None,
        completion,
    ));
    let mut response = Box::pin(client.request(request));
    let response = await_response_headers(
        response.as_mut(),
        &mut captured_connection,
        None,
        tokio::time::Instant::now() + WATCHDOG,
    )
    .await
    .unwrap()
    .unwrap();
    let guard = captured_connection_guard(captured_connection).unwrap();
    (response, guard)
}

async fn serve_healthy(server: DuplexStream, requests: usize, stopped: oneshot::Receiver<()>) {
    let mut server = BufReader::new(server);
    for _ in 0..requests {
        let Some(head) = read_head(&mut server).await else {
            return;
        };
        if head.starts_with("POST ") {
            assert!(head.contains("content-length: 8\r\n"));
            let mut body = [0; 8];
            server.read_exact(&mut body).await.unwrap();
            assert_eq!(&body, b"complete");
        } else {
            assert!(head.starts_with("GET "));
        }
        server.get_mut().write_all(HEALTHY_RESPONSE).await.unwrap();
    }
    let _stopped = stopped.await;
}

async fn read_head(server: &mut BufReader<DuplexStream>) -> Option<String> {
    let mut head = String::new();
    loop {
        let mut line = String::new();
        if server.read_line(&mut line).await.unwrap() == 0 {
            return None;
        }
        head.push_str(&line);
        if line == "\r\n" {
            return Some(head);
        }
    }
}

async fn read_chunked_body(server: &mut BufReader<DuplexStream>) {
    loop {
        let mut length = String::new();
        assert_ne!(server.read_line(&mut length).await.unwrap(), 0);
        let length = usize::from_str_radix(length.trim(), 16).unwrap();
        let mut chunk = vec![0; length + 2];
        server.read_exact(&mut chunk).await.unwrap();
        assert_eq!(&chunk[length..], b"\r\n");
        if length == 0 {
            return;
        }
    }
}

fn runtime() -> tokio::runtime::Runtime {
    Builder::new_current_thread().enable_time().build().unwrap()
}

fn client(connections: Vec<DuplexStream>, metrics: Arc<Metrics>) -> NativeClient {
    let connector = DuplexConnector(Arc::new(Mutex::new(VecDeque::from(connections))));
    let connector = InstrumentedConnector::new(
        connector,
        metrics,
        ConnectionGate::new(Some(1), None),
        IDLE_TIMEOUT,
        None,
    );
    Client::builder(RequestTaskContextExecutor)
        .pool_max_idle_per_host(1)
        .build(connector)
}

#[derive(Clone)]
struct DuplexConnector(Arc<Mutex<VecDeque<DuplexStream>>>);

impl Service<Uri> for DuplexConnector {
    type Response = DuplexConnection;
    type Error = Error;
    type Future = Ready<Result<Self::Response, Self::Error>>;

    fn poll_ready(&mut self, _context: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        Poll::Ready(Ok(()))
    }

    fn call(&mut self, _uri: Uri) -> Self::Future {
        ready(
            self.0
                .lock()
                .unwrap()
                .pop_front()
                .map(|io| DuplexConnection(TokioIo::new(io)))
                .ok_or_else(|| Error::new(ErrorKind::ConnectionRefused, "no test connection left")),
        )
    }
}

struct DuplexConnection(TokioIo<DuplexStream>);

impl Connection for DuplexConnection {
    fn connected(&self) -> Connected {
        Connected::new()
    }
}

impl Read for DuplexConnection {
    fn poll_read(
        self: Pin<&mut Self>,
        context: &mut Context<'_>,
        buffer: ReadBufCursor<'_>,
    ) -> Poll<Result<(), Error>> {
        Pin::new(&mut self.get_mut().0).poll_read(context, buffer)
    }
}

impl Write for DuplexConnection {
    fn poll_write(
        self: Pin<&mut Self>,
        context: &mut Context<'_>,
        buffer: &[u8],
    ) -> Poll<Result<usize, Error>> {
        Pin::new(&mut self.get_mut().0).poll_write(context, buffer)
    }

    fn poll_flush(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Result<(), Error>> {
        Pin::new(&mut self.get_mut().0).poll_flush(context)
    }

    fn poll_shutdown(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Result<(), Error>> {
        Pin::new(&mut self.get_mut().0).poll_shutdown(context)
    }
}
