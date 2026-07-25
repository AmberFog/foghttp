use super::{
    ConnectionAbortReason, ConnectionTelemetry, InstrumentedConnection, WriteTimeoutState,
};
use crate::core::client::{
    request_write_timeout_from_error, with_request_write_timeout, ConnectionGate,
    InstrumentedConnector, RequestTaskContextExecutor, RequestWriteTimeoutContext,
};
use crate::core::metrics::{Metrics, OriginMetricsSnapshot, ResponseBodyLifecycleOutcome};
use crate::core::telemetry::{
    with_request_telemetry, ClientTelemetry, TelemetryErrorType, TelemetryEventType,
    TelemetryOutcome, TelemetryRequestMode,
};
use bytes::Bytes;
use http_body_util::Full;
use hyper::rt::{Read, ReadBufCursor, Write};
use hyper::{Request, Uri};
use hyper_util::client::legacy::connect::{Connected, Connection};
use hyper_util::client::legacy::Client;
use std::future::{poll_fn, ready, Ready};
use std::io::{Error, ErrorKind, IoSlice};
use std::pin::Pin;
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll};
use std::time::Duration;
use tokio::runtime::{Builder, Runtime};
use tower_service::Service;

const HTTP_ORIGIN: &str = "http://api.example.com";
const ORIGIN: &str = "https://api.example.com";
const IDLE_TIMEOUT: Duration = Duration::from_secs(30);
const WRITE_TIMEOUT: Duration = Duration::from_millis(10);

#[test]
fn telemetry_tracks_reuse_idle_abort_and_close_once() {
    let metrics = Arc::new(Metrics::default());
    let origin_metrics = metrics.origin_metrics(ORIGIN);
    let telemetry =
        ConnectionTelemetry::new(Arc::clone(&metrics), Some(origin_metrics), IDLE_TIMEOUT);

    telemetry
        .request_started(None)
        .finish(ResponseBodyLifecycleOutcome::ReuseEligible);
    drop(telemetry.request_started(None));
    telemetry.connection_closed();
    telemetry.connection_closed();

    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.active_connections, 0);
    assert_eq!(snapshot.idle_connections, 0);
    assert_eq!(snapshot.connections_opened, 1);
    assert_eq!(snapshot.connections_closed, 1);
    assert_eq!(snapshot.connections_reused, 1);
    assert_eq!(snapshot.connections_aborted, 1);
    assert_eq!(snapshot.idle_timeout_evictions, 0);

    let origin_snapshot = origin_snapshot(&metrics);
    assert_eq!(origin_snapshot.active_connections, 0);
    assert_eq!(origin_snapshot.idle_connections, 0);
    assert_eq!(origin_snapshot.connections_opened, 1);
    assert_eq!(origin_snapshot.connections_closed, 1);
    assert_eq!(origin_snapshot.connections_reused, 1);
    assert_eq!(origin_snapshot.connections_aborted, 1);
    assert_eq!(origin_snapshot.idle_timeout_evictions, 0);
}

#[test]
fn connection_abort_preserves_typed_cancellation_context() {
    let metrics = Arc::new(Metrics::default());
    let client_telemetry = ClientTelemetry::new();
    let request_telemetry =
        client_telemetry.request(1, TelemetryRequestMode::Stream, "GET".to_owned());
    let connection = ConnectionTelemetry::new_with_native_telemetry(
        Arc::clone(&metrics),
        None,
        IDLE_TIMEOUT,
        client_telemetry
            .connection_open(Some(ORIGIN.to_owned()), None)
            .opened(),
        Some(ORIGIN.to_owned()),
    );

    connection.abort(Some(&request_telemetry), ConnectionAbortReason::Cancelled);

    let event = client_telemetry
        .drain(Some(1))
        .events
        .pop()
        .expect("connection abort event");
    assert_eq!(event.event_type, TelemetryEventType::ConnectionAborted);
    assert_eq!(event.outcome, Some(TelemetryOutcome::Cancelled));
    assert_eq!(event.error_type, Some(TelemetryErrorType::CancelledError));
}

#[test]
fn request_cancellation_claims_connection_abort_before_guard_drop() {
    runtime().block_on(async {
        let metrics = Arc::new(Metrics::default());
        let client_telemetry = ClientTelemetry::new();
        let request_telemetry =
            client_telemetry.request(1, TelemetryRequestMode::Buffered, "GET".to_owned());
        let connection = ConnectionTelemetry::new_with_native_telemetry(
            Arc::clone(&metrics),
            None,
            IDLE_TIMEOUT,
            client_telemetry
                .connection_open(Some(ORIGIN.to_owned()), None)
                .opened(),
            Some(ORIGIN.to_owned()),
        );
        let _ = client_telemetry.drain(None);
        let connection_use = connection.request_started(Some(request_telemetry.clone()));

        request_telemetry.cancel();
        drop(connection_use);

        let event = client_telemetry
            .drain(Some(1))
            .events
            .into_iter()
            .find(|event| event.event_type == TelemetryEventType::ConnectionAborted)
            .expect("connection abort event");
        assert_eq!(event.outcome, Some(TelemetryOutcome::Cancelled));
        assert_eq!(metrics.snapshot().connections_aborted, 1);
    });
}

#[test]
fn superseded_connection_assignment_leaves_terminal_outcome_to_the_replacement() {
    let metrics = Arc::new(Metrics::default());
    let client_telemetry = ClientTelemetry::new();
    let request_telemetry =
        client_telemetry.request(1, TelemetryRequestMode::Buffered, "GET".to_owned());
    let connection = || {
        ConnectionTelemetry::new_with_native_telemetry(
            Arc::clone(&metrics),
            None,
            IDLE_TIMEOUT,
            client_telemetry
                .connection_open(Some(ORIGIN.to_owned()), None)
                .opened(),
            Some(ORIGIN.to_owned()),
        )
    };
    let first = connection();
    let second = connection();
    let _ = client_telemetry.drain(None);

    first
        .request_started(Some(request_telemetry.clone()))
        .superseded();
    second
        .request_started(Some(request_telemetry))
        .abort(ConnectionAbortReason::Cancelled);

    let events = client_telemetry.drain(Some(1)).events;
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].event_type, TelemetryEventType::ConnectionAborted);
    assert_eq!(events[0].outcome, Some(TelemetryOutcome::Cancelled));
    assert_eq!(metrics.snapshot().connections_aborted, 1);
}

#[test]
fn closed_connection_does_not_reenter_idle_after_successful_body_finish() {
    let metrics = Arc::new(Metrics::default());
    let origin_metrics = metrics.origin_metrics(ORIGIN);
    let telemetry =
        ConnectionTelemetry::new(Arc::clone(&metrics), Some(origin_metrics), IDLE_TIMEOUT);
    let connection_use = telemetry.request_started(None);

    telemetry.connection_closed();
    connection_use.finish(ResponseBodyLifecycleOutcome::ReuseEligible);

    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.active_connections, 0);
    assert_eq!(snapshot.idle_connections, 0);
    assert_eq!(snapshot.connections_opened, 1);
    assert_eq!(snapshot.connections_closed, 1);
    assert_eq!(snapshot.connections_reused, 0);
    assert_eq!(snapshot.connections_aborted, 0);
    assert_eq!(snapshot.idle_timeout_evictions, 0);

    let origin_snapshot = origin_snapshot(&metrics);
    assert_eq!(origin_snapshot.active_connections, 0);
    assert_eq!(origin_snapshot.idle_connections, 0);
    assert_eq!(origin_snapshot.connections_opened, 1);
    assert_eq!(origin_snapshot.connections_closed, 1);
    assert_eq!(origin_snapshot.connections_reused, 0);
    assert_eq!(origin_snapshot.connections_aborted, 0);
    assert_eq!(origin_snapshot.idle_timeout_evictions, 0);
}

#[test]
fn idle_connection_closed_after_timeout_records_idle_timeout_eviction() {
    let metrics = Arc::new(Metrics::default());
    let origin_metrics = metrics.origin_metrics(ORIGIN);
    let telemetry =
        ConnectionTelemetry::new(Arc::clone(&metrics), Some(origin_metrics), Duration::ZERO);

    telemetry
        .request_started(None)
        .finish(ResponseBodyLifecycleOutcome::ReuseEligible);
    telemetry.connection_closed();

    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.active_connections, 0);
    assert_eq!(snapshot.idle_connections, 0);
    assert_eq!(snapshot.connections_closed, 1);
    assert_eq!(snapshot.idle_timeout_evictions, 1);

    let origin_snapshot = origin_snapshot(&metrics);
    assert_eq!(origin_snapshot.active_connections, 0);
    assert_eq!(origin_snapshot.idle_connections, 0);
    assert_eq!(origin_snapshot.connections_closed, 1);
    assert_eq!(origin_snapshot.idle_timeout_evictions, 1);
}

#[test]
fn reused_idle_connection_does_not_record_idle_timeout_eviction() {
    let metrics = Arc::new(Metrics::default());
    let origin_metrics = metrics.origin_metrics(ORIGIN);
    let telemetry =
        ConnectionTelemetry::new(Arc::clone(&metrics), Some(origin_metrics), IDLE_TIMEOUT);

    telemetry
        .request_started(None)
        .finish(ResponseBodyLifecycleOutcome::ReuseEligible);
    drop(telemetry.request_started(None));
    telemetry.connection_closed();

    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.connections_reused, 1);
    assert_eq!(snapshot.connections_aborted, 1);
    assert_eq!(snapshot.idle_timeout_evictions, 0);

    let origin_snapshot = origin_snapshot(&metrics);
    assert_eq!(origin_snapshot.connections_reused, 1);
    assert_eq!(origin_snapshot.connections_aborted, 1);
    assert_eq!(origin_snapshot.idle_timeout_evictions, 0);
}

#[test]
fn pending_socket_write_expires_request_write_timeout() {
    runtime().block_on(async {
        let metrics = Arc::new(Metrics::default());
        let mut connection = pending_write_connection(Arc::clone(&metrics));
        let telemetry = ClientTelemetry::new();
        let request_telemetry =
            telemetry.request(1, TelemetryRequestMode::Buffered, "POST".to_owned());

        let result = with_request_telemetry(
            Some(request_telemetry),
            with_request_write_timeout(
                Some(RequestWriteTimeoutContext::new(
                    WRITE_TIMEOUT,
                    WRITE_TIMEOUT.as_secs_f64(),
                    ORIGIN.to_owned(),
                    0,
                )),
                async {
                    tokio::time::timeout(Duration::from_secs(1), async {
                        poll_fn(|context| {
                            Pin::new(&mut connection).poll_write(context, b"request body")
                        })
                        .await
                    })
                    .await
                    .expect("expected write timeout before test timeout")
                },
            ),
        )
        .await;

        let error = result.expect_err("expected pending write to time out");
        assert_eq!(error.kind(), ErrorKind::TimedOut);
        assert_eq!(error.to_string(), "request body write timeout expired");
        assert_eq!(metrics.snapshot().connections_aborted, 1);
        let event = telemetry
            .drain(Some(1))
            .events
            .into_iter()
            .find(|event| event.event_type == TelemetryEventType::ConnectionAborted)
            .expect("expected connection abort telemetry event");
        assert_eq!(event.error_type, Some(TelemetryErrorType::WriteTimeout));
    });
}

#[test]
fn hyper_dispatcher_sees_write_timeout_context_on_isolated_client() {
    runtime().block_on(async {
        let metrics = Arc::new(Metrics::default());
        let connector = InstrumentedConnector::new(
            PendingConnector,
            Arc::clone(&metrics),
            ConnectionGate::new(Some(1), None),
            IDLE_TIMEOUT,
            None,
        );
        let client = Client::builder(RequestTaskContextExecutor)
            .pool_max_idle_per_host(0)
            .build(connector);
        let request = Request::builder()
            .method("POST")
            .uri(HTTP_ORIGIN)
            .body(Full::new(Bytes::from_static(b"request body")))
            .unwrap();

        let result = with_request_write_timeout(
            Some(RequestWriteTimeoutContext::new(
                WRITE_TIMEOUT,
                WRITE_TIMEOUT.as_secs_f64(),
                HTTP_ORIGIN.to_owned(),
                0,
            )),
            async {
                tokio::time::timeout(Duration::from_secs(1), client.request(request))
                    .await
                    .expect("expected dispatcher write timeout before test timeout")
            },
        )
        .await;

        let error = result.expect_err("expected request write timeout");
        let timeout = request_write_timeout_from_error(&error)
            .expect("expected write timeout through real hyper dispatcher path");
        assert_eq!(timeout.origin(), HTTP_ORIGIN);
        assert_eq!(metrics.snapshot().connections_aborted, 1);
    });
}

#[test]
fn successful_socket_write_resets_request_write_timeout() {
    runtime().block_on(async {
        let metrics = Arc::new(Metrics::default());
        let inner = FakeConnection::with_write_sequence([
            Poll::Pending,
            Poll::Ready(Ok(4)),
            Poll::Pending,
            Poll::Ready(Ok(4)),
        ]);
        let writes = Arc::clone(&inner.writes);
        let mut connection = instrumented_connection(inner, metrics);

        let result = with_request_write_timeout(
            Some(RequestWriteTimeoutContext::new(
                Duration::from_secs(1),
                1.0,
                ORIGIN.to_owned(),
                0,
            )),
            async {
                poll_fn(|context| Pin::new(&mut connection).poll_write(context, b"body")).await?;
                poll_fn(|context| Pin::new(&mut connection).poll_write(context, b"body")).await
            },
        )
        .await;

        assert_eq!(result.unwrap(), 4);
        assert_eq!(*writes.lock().unwrap(), 2);
    });
}

#[derive(Clone, Copy)]
struct PendingConnector;

impl Service<Uri> for PendingConnector {
    type Response = FakeConnection;
    type Error = Error;
    type Future = Ready<Result<Self::Response, Self::Error>>;

    fn poll_ready(&mut self, _context: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        Poll::Ready(Ok(()))
    }

    fn call(&mut self, _uri: Uri) -> Self::Future {
        ready(Ok(FakeConnection::always_pending()))
    }
}

fn origin_snapshot(metrics: &Metrics) -> OriginMetricsSnapshot {
    metrics
        .origin_snapshots()
        .into_iter()
        .find(|snapshot| snapshot.origin == ORIGIN)
        .expect("expected origin metrics snapshot")
}

fn runtime() -> Runtime {
    Builder::new_current_thread()
        .enable_time()
        .build()
        .expect("expected Tokio runtime")
}

fn pending_write_connection(metrics: Arc<Metrics>) -> InstrumentedConnection<FakeConnection> {
    instrumented_connection(FakeConnection::always_pending(), metrics)
}

fn instrumented_connection(
    inner: FakeConnection,
    metrics: Arc<Metrics>,
) -> InstrumentedConnection<FakeConnection> {
    let origin_metrics = metrics.origin_metrics(ORIGIN);
    InstrumentedConnection {
        inner,
        telemetry: ConnectionTelemetry::new_with_native_telemetry(
            metrics,
            Some(origin_metrics),
            IDLE_TIMEOUT,
            None,
            Some(ORIGIN.to_owned()),
        ),
        write_timeout: WriteTimeoutState::default(),
        _connection_permit: crate::core::client::connection_limit::ConnectionPermit::default(),
    }
}

struct FakeConnection {
    write_sequence: Vec<Poll<Result<usize, Error>>>,
    writes: Arc<Mutex<usize>>,
}

impl FakeConnection {
    fn always_pending() -> Self {
        Self {
            write_sequence: Vec::new(),
            writes: Arc::new(Mutex::new(0)),
        }
    }

    fn with_write_sequence<const N: usize>(sequence: [Poll<Result<usize, Error>>; N]) -> Self {
        Self {
            write_sequence: Vec::from(sequence).into_iter().rev().collect(),
            writes: Arc::new(Mutex::new(0)),
        }
    }

    fn poll_next_write(
        &mut self,
        context: &mut Context<'_>,
        buffer_len: usize,
    ) -> Poll<Result<usize, Error>> {
        match self.write_sequence.pop() {
            Some(Poll::Ready(Ok(written))) => {
                *self.writes.lock().unwrap() += 1;
                Poll::Ready(Ok(written.min(buffer_len)))
            }
            Some(Poll::Ready(Err(error))) => Poll::Ready(Err(error)),
            Some(Poll::Pending) | None => {
                context.waker().wake_by_ref();
                Poll::Pending
            }
        }
    }
}

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
        Poll::Pending
    }
}

impl Write for FakeConnection {
    fn poll_write(
        self: Pin<&mut Self>,
        context: &mut Context<'_>,
        buffer: &[u8],
    ) -> Poll<Result<usize, Error>> {
        self.get_mut().poll_next_write(context, buffer.len())
    }

    fn poll_flush(self: Pin<&mut Self>, _context: &mut Context<'_>) -> Poll<Result<(), Error>> {
        Poll::Ready(Ok(()))
    }

    fn poll_shutdown(self: Pin<&mut Self>, _context: &mut Context<'_>) -> Poll<Result<(), Error>> {
        Poll::Ready(Ok(()))
    }

    fn is_write_vectored(&self) -> bool {
        true
    }

    fn poll_write_vectored(
        self: Pin<&mut Self>,
        context: &mut Context<'_>,
        buffers: &[IoSlice<'_>],
    ) -> Poll<Result<usize, Error>> {
        let total_len = buffers.iter().map(|buffer| buffer.len()).sum();
        self.get_mut().poll_next_write(context, total_len)
    }
}
