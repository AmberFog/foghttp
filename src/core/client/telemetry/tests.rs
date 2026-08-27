use super::{ConnectionAbortReason, ConnectionTelemetry, InstrumentedConnection};
use crate::core::client::{
    buffered_request_body, request_write_timeout_from_error, streaming_request_body,
    upload_body_channel, ConnectionGate, InstrumentedConnector, RequestTaskContextExecutor,
    RequestWriteTimeoutContext,
};
use crate::core::metrics::{Metrics, OriginMetricsSnapshot, ResponseBodyLifecycleOutcome};
use crate::core::telemetry::{
    ClientTelemetry, TelemetryErrorType, TelemetryEventType, TelemetryOutcome, TelemetryRequestMode,
};
use bytes::Bytes;
use http_body_util::{BodyExt, Full};
use hyper::rt::{Read, ReadBufCursor, Write};
use hyper::{http::Extensions, Request, Uri};
use hyper_util::client::legacy::connect::{capture_connection, Connected, Connection};
use hyper_util::client::legacy::Client;
use std::future::{poll_fn, ready, Future, Ready};
use std::io::{Error, ErrorKind, IoSlice};
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll, Wake, Waker};
use std::time::Duration;
use tokio::runtime::{Builder, Runtime};
use tower_service::Service;

const HTTP_ORIGIN: &str = "http://api.example.com";
const ORIGIN: &str = "https://api.example.com";
const SECOND_ORIGIN: &str = "https://uploads.example.com";
const IDLE_TIMEOUT: Duration = Duration::from_secs(30);
const WRITE_TIMEOUT: Duration = Duration::from_millis(10);
const SECOND_WRITE_TIMEOUT: Duration = Duration::from_millis(50);

#[test]
fn telemetry_tracks_reuse_idle_abort_and_close_once() {
    let metrics = Arc::new(Metrics::default());
    let origin_metrics = metrics.origin_metrics(ORIGIN);
    let telemetry =
        ConnectionTelemetry::new(Arc::clone(&metrics), Some(origin_metrics), IDLE_TIMEOUT);

    telemetry
        .request_started(None, None)
        .finish(ResponseBodyLifecycleOutcome::ReuseEligible);
    drop(telemetry.request_started(None, None));
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
fn repeated_physical_abort_preserves_each_logical_abort_outcome() {
    let metrics = Arc::new(Metrics::default());
    let client_telemetry = ClientTelemetry::new();
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

    let first_request =
        client_telemetry.request(1, TelemetryRequestMode::Buffered, "POST".to_owned());
    connection
        .request_started(Some(first_request), None)
        .abort(ConnectionAbortReason::Closed);
    let second_request =
        client_telemetry.request(2, TelemetryRequestMode::Buffered, "POST".to_owned());
    connection
        .request_started(Some(second_request), None)
        .abort(ConnectionAbortReason::Cancelled);

    let first_event = client_telemetry
        .drain(Some(1))
        .events
        .pop()
        .expect("first connection abort event");
    assert_eq!(
        first_event.event_type,
        TelemetryEventType::ConnectionAborted
    );
    assert_eq!(first_event.outcome, Some(TelemetryOutcome::Closed));
    assert_eq!(first_event.error_type, None);

    let second_event = client_telemetry
        .drain(Some(2))
        .events
        .pop()
        .expect("second connection abort event");
    assert_eq!(
        second_event.event_type,
        TelemetryEventType::ConnectionAborted
    );
    assert_eq!(second_event.outcome, Some(TelemetryOutcome::Cancelled));
    assert_eq!(
        second_event.error_type,
        Some(TelemetryErrorType::CancelledError),
    );
    assert_eq!(metrics.snapshot().connections_aborted, 1);
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
        let connection_use = connection.request_started(Some(request_telemetry.clone()), None);

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
fn late_write_timeout_does_not_duplicate_cancelled_connection_abort() {
    let metrics = Arc::new(Metrics::default());
    let client_telemetry = ClientTelemetry::new();
    let request_telemetry =
        client_telemetry.request(1, TelemetryRequestMode::Buffered, "POST".to_owned());
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
    let connection_use = connection.request_started(Some(request_telemetry.clone()), None);

    request_telemetry.cancel();
    connection.abort(
        Some(&request_telemetry),
        ConnectionAbortReason::Error(Some(TelemetryErrorType::WriteTimeout)),
    );
    drop(connection_use);

    let events = client_telemetry
        .drain(Some(1))
        .events
        .into_iter()
        .filter(|event| event.event_type == TelemetryEventType::ConnectionAborted)
        .collect::<Vec<_>>();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].outcome, Some(TelemetryOutcome::Cancelled));
    assert_eq!(
        events[0].error_type,
        Some(TelemetryErrorType::CancelledError)
    );
    assert_eq!(metrics.snapshot().connections_aborted, 1);
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
        .request_started(Some(request_telemetry.clone()), None)
        .superseded();
    second
        .request_started(Some(request_telemetry), None)
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
    let connection_use = telemetry.request_started(None, None);

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
fn incomplete_request_body_aborts_instead_of_entering_idle() {
    let metrics = Arc::new(Metrics::default());
    let telemetry = ConnectionTelemetry::new(Arc::clone(&metrics), None, IDLE_TIMEOUT);
    let (_body, completion) = buffered_request_body(Some(b"request body".to_vec()));
    let connection_use =
        telemetry.request_started_with_body_completion(None, None, Some(completion));

    connection_use.finish(ResponseBodyLifecycleOutcome::ReuseEligible);

    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.idle_connections, 0);
    assert_eq!(snapshot.connections_aborted, 1);
}

#[test]
fn incomplete_request_body_aborts_when_response_closes_connection() {
    let metrics = Arc::new(Metrics::default());
    let telemetry = ConnectionTelemetry::new(Arc::clone(&metrics), None, IDLE_TIMEOUT);
    let (_body, completion) = buffered_request_body(Some(b"request body".to_vec()));
    let connection_use =
        telemetry.request_started_with_body_completion(None, None, Some(completion));

    connection_use.finish(ResponseBodyLifecycleOutcome::Closed);

    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.idle_connections, 0);
    assert_eq!(snapshot.connections_aborted, 1);
}

fn assert_inexact_known_length_upload_aborts(chunk: &'static [u8]) {
    let (sender, receiver) = upload_body_channel(1);
    let (mut body, completion) = streaming_request_body(receiver, Some(5), None);
    assert_eq!(
        sender.send_final_nowait(Ok(Bytes::from_static(chunk))),
        Ok(())
    );

    let frame = runtime()
        .block_on(body.frame())
        .expect("request body frame")
        .expect("successful request body frame")
        .into_data()
        .expect("request body data");
    drop(frame);
    completion.mark_transport_flushed();
    assert!(!completion.is_complete());

    let metrics = Arc::new(Metrics::default());
    let telemetry = ConnectionTelemetry::new(Arc::clone(&metrics), None, IDLE_TIMEOUT);
    telemetry
        .request_started_with_body_completion(None, None, Some(completion))
        .finish(ResponseBodyLifecycleOutcome::ReuseEligible);

    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.connections_aborted, 1);
    assert_eq!(snapshot.idle_connections, 0);
}

#[test]
fn short_known_length_upload_aborts_instead_of_entering_idle() {
    assert_inexact_known_length_upload_aborts(b"abc");
}

#[test]
fn oversized_known_length_upload_aborts_instead_of_entering_idle() {
    assert_inexact_known_length_upload_aborts(b"oversized");
}

#[test]
fn aborted_connection_does_not_reenter_idle_after_a_new_assignment() {
    let metrics = Arc::new(Metrics::default());
    let telemetry = ConnectionTelemetry::new(Arc::clone(&metrics), None, IDLE_TIMEOUT);
    let (_body, completion) = buffered_request_body(Some(b"request body".to_vec()));
    let stale_use = telemetry.request_started_with_body_completion(None, None, Some(completion));
    let current_use = telemetry.request_started(None, None);

    assert_eq!(metrics.snapshot().connections_aborted, 1);
    stale_use.finish(ResponseBodyLifecycleOutcome::ReuseEligible);
    assert_eq!(metrics.snapshot().connections_aborted, 1);
    current_use.finish(ResponseBodyLifecycleOutcome::ReuseEligible);

    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.connections_aborted, 1);
    assert_eq!(snapshot.idle_connections, 0);
}

#[test]
fn stale_incomplete_abort_still_invalidates_the_physical_connection() {
    let metrics = Arc::new(Metrics::default());
    let telemetry = ConnectionTelemetry::new(Arc::clone(&metrics), None, IDLE_TIMEOUT);
    let (_body, completion) = buffered_request_body(Some(b"request body".to_vec()));
    let stale_use = telemetry.request_started_with_body_completion(None, None, Some(completion));

    telemetry.inner.observed_uses.fetch_add(1, Ordering::AcqRel);
    stale_use.abort(ConnectionAbortReason::Cancelled);

    assert_eq!(metrics.snapshot().connections_aborted, 1);
}

#[test]
fn stale_incomplete_guard_drop_still_invalidates_the_physical_connection() {
    let metrics = Arc::new(Metrics::default());
    let telemetry = ConnectionTelemetry::new(Arc::clone(&metrics), None, IDLE_TIMEOUT);
    let (_body, completion) = buffered_request_body(Some(b"request body".to_vec()));
    let stale_use = telemetry.request_started_with_body_completion(None, None, Some(completion));

    telemetry.inner.observed_uses.fetch_add(1, Ordering::AcqRel);
    drop(stale_use);

    assert_eq!(metrics.snapshot().connections_aborted, 1);
}

#[test]
fn successful_flush_completes_unknown_length_request_body() {
    runtime().block_on(async {
        let (sender, receiver) = upload_body_channel(1);
        let (body, completion) = streaming_request_body(receiver, None, None);
        assert_eq!(sender.send_nowait(Ok(Bytes::from_static(b"chunk"))), Ok(()));
        sender.finish();
        let collected = body.collect().await.unwrap().to_bytes();
        drop(collected);
        assert!(!completion.is_complete());

        let metrics = Arc::new(Metrics::default());
        let mut connection = instrumented_connection(
            FakeConnection::with_write_sequence([Poll::Ready(Ok(1))]),
            Arc::clone(&metrics),
        );
        let connection_use = connection.telemetry.request_started_with_body_completion(
            None,
            None,
            Some(completion.clone()),
        );
        poll_fn(|context| Pin::new(&mut connection).poll_write(context, b"request"))
            .await
            .unwrap();
        poll_fn(|context| Pin::new(&mut connection).poll_flush(context))
            .await
            .unwrap();
        assert!(completion.is_complete());

        connection_use.finish(ResponseBodyLifecycleOutcome::ReuseEligible);
        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.connections_aborted, 0);
        assert_eq!(snapshot.idle_connections, 1);
    });
}

#[test]
fn idle_flush_before_bodyless_request_write_does_not_complete_body() {
    runtime().block_on(async {
        let (_body, completion) = buffered_request_body(None);

        let metrics = Arc::new(Metrics::default());
        let mut connection = instrumented_connection(
            FakeConnection::with_write_sequence([Poll::Ready(Ok(1))]),
            Arc::clone(&metrics),
        );
        let wake_flag = Arc::new(WakeFlag::default());
        let waker = Waker::from(Arc::clone(&wake_flag));
        let mut context = Context::from_waker(&waker);

        assert!(Pin::new(&mut connection)
            .poll_flush(&mut context)
            .is_ready());
        assert!(!completion.is_complete());
        wake_flag.0.store(false, Ordering::Release);

        let connection_use = connection.telemetry.request_started_with_body_completion(
            None,
            None,
            Some(completion.clone()),
        );
        assert!(wake_flag.0.load(Ordering::Acquire));
        assert!(Pin::new(&mut connection)
            .poll_flush(&mut context)
            .is_ready());
        assert!(!completion.is_complete());
        assert!(Pin::new(&mut connection)
            .poll_write(&mut context, b"request")
            .is_ready());
        assert!(Pin::new(&mut connection)
            .poll_flush(&mut context)
            .is_ready());
        assert!(completion.is_complete());

        connection_use.finish(ResponseBodyLifecycleOutcome::ReuseEligible);
        assert_eq!(metrics.snapshot().idle_connections, 1);
    });
}

#[test]
fn completed_upload_requires_a_flush_after_the_last_in_flight_frame() {
    runtime().block_on(async {
        let (body, completion) = buffered_request_body(Some(b"request body".to_vec()));
        let collected = body.collect().await.unwrap().to_bytes();
        let metrics = Arc::new(Metrics::default());
        let inner = FakeConnection::with_write_sequence([Poll::Ready(Ok(1)), Poll::Ready(Ok(1))]);
        let writes = Arc::clone(&inner.writes);
        let mut connection = instrumented_connection(inner, metrics);
        let old_use = connection.telemetry.request_started_with_body_completion(
            None,
            None,
            Some(completion.clone()),
        );
        let wake_flag = Arc::new(WakeFlag::default());
        let waker = Waker::from(Arc::clone(&wake_flag));
        let mut context = Context::from_waker(&waker);

        assert!(Pin::new(&mut connection)
            .poll_write(&mut context, b"request")
            .is_ready());
        assert!(Pin::new(&mut connection)
            .poll_flush(&mut context)
            .is_ready());
        assert!(!completion.is_complete());
        assert!(connection.telemetry.lock_write_timeout().active.is_some());
        drop(collected);
        assert!(!completion.is_complete());

        assert!(Pin::new(&mut connection)
            .poll_flush(&mut context)
            .is_ready());
        assert!(completion.is_complete());

        wake_flag.0.store(false, Ordering::Release);
        assert!(Pin::new(&mut connection)
            .poll_write(&mut context, b"next request")
            .is_pending());
        assert_eq!(*writes.lock().unwrap(), 1);
        assert!(connection.telemetry.lock_write_timeout().active.is_none());

        let current_use = connection.telemetry.request_started(None, None);
        assert!(wake_flag.0.load(Ordering::Acquire));
        assert!(Pin::new(&mut connection)
            .poll_write(&mut context, b"next request")
            .is_ready());
        assert_eq!(*writes.lock().unwrap(), 2);

        old_use.finish(ResponseBodyLifecycleOutcome::ReuseEligible);
        assert_eq!(
            connection
                .telemetry
                .lock_write_timeout()
                .active
                .as_ref()
                .map(|active| active.use_id),
            Some(1),
        );
        current_use.abort(ConnectionAbortReason::Closed);
    });
}

#[test]
fn unflushed_unknown_length_request_body_aborts_instead_of_entering_idle() {
    runtime().block_on(async {
        let (sender, receiver) = upload_body_channel(1);
        let (body, completion) = streaming_request_body(receiver, None, None);
        assert_eq!(sender.send_nowait(Ok(Bytes::from_static(b"chunk"))), Ok(()));
        sender.finish();
        drop(body.collect().await.unwrap().to_bytes());
        assert!(!completion.is_complete());

        let metrics = Arc::new(Metrics::default());
        let telemetry = ConnectionTelemetry::new(Arc::clone(&metrics), None, IDLE_TIMEOUT);
        telemetry
            .request_started_with_body_completion(None, None, Some(completion))
            .finish(ResponseBodyLifecycleOutcome::ReuseEligible);

        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.connections_aborted, 1);
        assert_eq!(snapshot.idle_connections, 0);
    });
}

#[test]
fn aborted_wire_finished_upload_blocks_the_next_request_until_assignment() {
    runtime().block_on(async {
        let (sender, receiver) = upload_body_channel(1);
        let (body, completion) = streaming_request_body(receiver, None, None);
        sender.close();
        drop(body.collect().await.unwrap().to_bytes());

        let metrics = Arc::new(Metrics::default());
        let inner = FakeConnection::with_write_sequence([Poll::Ready(Ok(1))]);
        let writes = Arc::clone(&inner.writes);
        let mut connection = instrumented_connection(inner, Arc::clone(&metrics));
        let stale_use = connection.telemetry.request_started_with_body_completion(
            None,
            None,
            Some(completion.clone()),
        );
        let waker = Waker::noop();
        let mut context = Context::from_waker(waker);

        assert!(Pin::new(&mut connection)
            .poll_write(&mut context, b"request")
            .is_ready());
        assert!(Pin::new(&mut connection)
            .poll_flush(&mut context)
            .is_ready());
        assert!(completion.is_wire_finished());
        assert!(!completion.is_complete());
        assert!(Pin::new(&mut connection)
            .poll_write(&mut context, b"next request")
            .is_pending());
        assert_eq!(*writes.lock().unwrap(), 1);

        let current_use = connection.telemetry.request_started(None, None);
        let Poll::Ready(result) =
            Pin::new(&mut connection).poll_write(&mut context, b"next request")
        else {
            panic!("aborted connection must reject the next request immediately");
        };
        let error = result.expect_err("aborted connection cannot be reused");
        assert_eq!(error.kind(), ErrorKind::ConnectionAborted);
        assert_eq!(*writes.lock().unwrap(), 1);
        assert_eq!(metrics.snapshot().connections_aborted, 1);

        stale_use.finish(ResponseBodyLifecycleOutcome::ReuseEligible);
        current_use.abort(ConnectionAbortReason::Closed);
        assert_eq!(metrics.snapshot().connections_aborted, 1);
    });
}

#[test]
fn connection_abort_wakes_and_rejects_pending_io() {
    let metrics = Arc::new(Metrics::default());
    let telemetry = ConnectionTelemetry::new(metrics, None, IDLE_TIMEOUT);
    let wake_flag = Arc::new(WakeFlag::default());
    let waker = Waker::from(Arc::clone(&wake_flag));
    let context = Context::from_waker(&waker);
    assert!(telemetry.prepare_io_poll(&context).is_ok());

    telemetry
        .request_started(None, None)
        .abort(ConnectionAbortReason::Closed);

    assert!(wake_flag.0.load(Ordering::Acquire));
    let error = telemetry
        .prepare_io_poll(&context)
        .expect_err("aborted connection must reject further I/O");
    assert_eq!(error.kind(), ErrorKind::ConnectionAborted);
}

#[test]
fn connection_abort_wakes_and_rejects_pending_shutdown() {
    let metrics = Arc::new(Metrics::default());
    let inner = FakeConnection::with_pending_shutdown();
    let shutdowns = Arc::clone(&inner.shutdowns);
    let mut connection = instrumented_connection(inner, Arc::clone(&metrics));
    let wake_flag = Arc::new(WakeFlag::default());
    let waker = Waker::from(Arc::clone(&wake_flag));
    let mut context = Context::from_waker(&waker);

    assert!(Pin::new(&mut connection)
        .poll_shutdown(&mut context)
        .is_pending());
    assert_eq!(*shutdowns.lock().unwrap(), 1);

    connection
        .telemetry
        .request_started(None, None)
        .abort(ConnectionAbortReason::Closed);

    assert!(wake_flag.0.load(Ordering::Acquire));
    let Poll::Ready(result) = Pin::new(&mut connection).poll_shutdown(&mut context) else {
        panic!("aborted connection must reject shutdown immediately");
    };
    let error = result.expect_err("aborted connection cannot continue shutdown");
    assert_eq!(error.kind(), ErrorKind::ConnectionAborted);
    assert_eq!(*shutdowns.lock().unwrap(), 1);
    assert_eq!(metrics.snapshot().connections_aborted, 1);
}

#[test]
fn idle_connection_closed_after_timeout_records_idle_timeout_eviction() {
    let metrics = Arc::new(Metrics::default());
    let origin_metrics = metrics.origin_metrics(ORIGIN);
    let telemetry =
        ConnectionTelemetry::new(Arc::clone(&metrics), Some(origin_metrics), Duration::ZERO);

    telemetry
        .request_started(None, None)
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
        .request_started(None, None)
        .finish(ResponseBodyLifecycleOutcome::ReuseEligible);
    drop(telemetry.request_started(None, None));
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
        let _connection_use = connection.telemetry.request_started(
            Some(request_telemetry),
            Some(RequestWriteTimeoutContext::new(
                WRITE_TIMEOUT,
                WRITE_TIMEOUT.as_secs_f64(),
                ORIGIN.to_owned(),
                0,
            )),
        );

        let result = tokio::time::timeout(Duration::from_secs(1), async {
            poll_fn(|context| Pin::new(&mut connection).poll_write(context, b"request body")).await
        })
        .await
        .expect("expected write timeout before test timeout");

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
fn request_assignment_wakes_pending_write_without_consuming_timeout_budget() {
    runtime().block_on(async {
        let metrics = Arc::new(Metrics::default());
        let mut connection = pending_write_connection(metrics);
        let wake_flag = Arc::new(WakeFlag::default());
        let waker = Waker::from(Arc::clone(&wake_flag));
        let mut context = Context::from_waker(&waker);

        assert!(Pin::new(&mut connection)
            .poll_write(&mut context, b"request body")
            .is_pending());
        wake_flag.0.store(false, Ordering::Release);
        tokio::time::sleep(SECOND_WRITE_TIMEOUT * 2).await;

        let _connection_use = connection.telemetry.request_started(
            None,
            Some(RequestWriteTimeoutContext::new(
                SECOND_WRITE_TIMEOUT,
                SECOND_WRITE_TIMEOUT.as_secs_f64(),
                ORIGIN.to_owned(),
                0,
            )),
        );
        assert!(
            wake_flag.0.load(Ordering::Acquire),
            "request assignment did not wake the pending connection driver"
        );

        let early_result = tokio::time::timeout(
            SECOND_WRITE_TIMEOUT / 2,
            poll_fn(|context| Pin::new(&mut connection).poll_write(context, b"request body")),
        )
        .await;
        assert!(
            early_result.is_err(),
            "wait before assignment consumed the write timeout budget"
        );

        let error = tokio::time::timeout(
            Duration::from_secs(1),
            poll_fn(|context| Pin::new(&mut connection).poll_write(context, b"request body")),
        )
        .await
        .expect("expected write timeout before test timeout")
        .expect_err("expected request write timeout");
        let timeout = request_write_timeout_from_error(&error)
            .expect("expected assigned request write timeout context");
        assert_eq!(timeout.origin(), ORIGIN);
    });
}

#[test]
fn hyper_dispatcher_uses_assigned_write_timeout_on_pooled_client() {
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
            .pool_max_idle_per_host(1)
            .build(connector);
        let mut request = Request::builder()
            .method("POST")
            .uri(HTTP_ORIGIN)
            .body(Full::new(Bytes::from_static(b"request body")))
            .unwrap();
        let capture = capture_connection(&mut request);
        let write_timeout = RequestWriteTimeoutContext::new(
            WRITE_TIMEOUT,
            WRITE_TIMEOUT.as_secs_f64(),
            HTTP_ORIGIN.to_owned(),
            0,
        );
        let mut connection_use = None;
        let mut response = Box::pin(client.request(request));

        let result = tokio::time::timeout(
            Duration::from_secs(1),
            poll_fn(|context| {
                let response = response.as_mut().poll(context);
                if connection_use.is_none() {
                    let connection = {
                        let metadata = capture.connection_metadata();
                        metadata.as_ref().and_then(|connected| {
                            let mut extensions = Extensions::new();
                            connected.get_extras(&mut extensions);
                            extensions.get::<ConnectionTelemetry>().cloned()
                        })
                    };
                    if let Some(connection) = connection {
                        connection_use =
                            Some(connection.request_started(None, Some(write_timeout.clone())));
                    }
                }
                response
            }),
        )
        .await
        .expect("expected dispatcher write timeout before test timeout");

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
        let _connection_use = connection.telemetry.request_started(
            None,
            Some(RequestWriteTimeoutContext::new(
                Duration::from_secs(1),
                1.0,
                ORIGIN.to_owned(),
                0,
            )),
        );

        let result = async {
            poll_fn(|context| Pin::new(&mut connection).poll_write(context, b"body")).await?;
            poll_fn(|context| Pin::new(&mut connection).poll_write(context, b"body")).await
        }
        .await;

        assert_eq!(result.unwrap(), 4);
        assert_eq!(*writes.lock().unwrap(), 2);
    });
}

#[test]
fn zero_length_socket_write_does_not_reset_request_write_timeout() {
    runtime().block_on(async {
        let metrics = Arc::new(Metrics::default());
        let inner = FakeConnection::with_write_sequence([Poll::Pending, Poll::Ready(Ok(0))]);
        let mut connection = instrumented_connection(inner, metrics);
        let _connection_use = connection.telemetry.request_started(
            None,
            Some(RequestWriteTimeoutContext::new(
                WRITE_TIMEOUT,
                WRITE_TIMEOUT.as_secs_f64(),
                ORIGIN.to_owned(),
                0,
            )),
        );
        let waker = Waker::noop();
        let mut context = Context::from_waker(waker);

        assert!(Pin::new(&mut connection)
            .poll_write(&mut context, b"body")
            .is_pending());
        let pending_since = connection.telemetry.lock_write_timeout().pending_since;
        assert!(matches!(
            Pin::new(&mut connection).poll_write(&mut context, b"body"),
            Poll::Ready(Ok(0)),
        ));

        assert_eq!(
            connection.telemetry.lock_write_timeout().pending_since,
            pending_since,
        );
    });
}

#[test]
fn zero_length_vectored_write_does_not_reset_request_write_timeout() {
    runtime().block_on(async {
        let metrics = Arc::new(Metrics::default());
        let inner = FakeConnection::with_write_sequence([Poll::Pending, Poll::Ready(Ok(0))]);
        let mut connection = instrumented_connection(inner, metrics);
        let _connection_use = connection.telemetry.request_started(
            None,
            Some(RequestWriteTimeoutContext::new(
                WRITE_TIMEOUT,
                WRITE_TIMEOUT.as_secs_f64(),
                ORIGIN.to_owned(),
                0,
            )),
        );
        let waker = Waker::noop();
        let mut context = Context::from_waker(waker);
        let buffers = [IoSlice::new(b"body")];

        assert!(Pin::new(&mut connection)
            .poll_write_vectored(&mut context, &buffers)
            .is_pending());
        let pending_since = connection.telemetry.lock_write_timeout().pending_since;
        assert!(matches!(
            Pin::new(&mut connection).poll_write_vectored(&mut context, &buffers),
            Poll::Ready(Ok(0)),
        ));

        assert_eq!(
            connection.telemetry.lock_write_timeout().pending_since,
            pending_since,
        );
    });
}

#[test]
fn reused_connection_replaces_completed_request_write_timeout() {
    runtime().block_on(async {
        let metrics = Arc::new(Metrics::default());
        let mut connection = pending_write_connection(metrics);
        let first_use = connection.telemetry.request_started(
            None,
            Some(RequestWriteTimeoutContext::new(
                WRITE_TIMEOUT,
                WRITE_TIMEOUT.as_secs_f64(),
                ORIGIN.to_owned(),
                0,
            )),
        );
        let wake_flag = Arc::new(WakeFlag::default());
        let waker = Waker::from(Arc::clone(&wake_flag));
        let mut context = Context::from_waker(&waker);
        assert!(Pin::new(&mut connection)
            .poll_write(&mut context, b"first body")
            .is_pending());
        wake_flag.0.store(false, Ordering::Release);

        let _second_use = connection.telemetry.request_started(
            None,
            Some(RequestWriteTimeoutContext::new(
                SECOND_WRITE_TIMEOUT,
                SECOND_WRITE_TIMEOUT.as_secs_f64(),
                SECOND_ORIGIN.to_owned(),
                1,
            )),
        );
        assert!(
            wake_flag.0.load(Ordering::Acquire),
            "replacement request did not wake the pending connection driver"
        );
        first_use.finish(ResponseBodyLifecycleOutcome::ReuseEligible);
        assert_eq!(
            connection
                .telemetry
                .inner
                .metrics
                .snapshot()
                .idle_connections,
            0
        );
        let early_result = tokio::time::timeout(
            WRITE_TIMEOUT * 2,
            poll_fn(|context| Pin::new(&mut connection).poll_write(context, b"second body")),
        )
        .await;
        assert!(
            early_result.is_err(),
            "first request timeout leaked into reuse"
        );

        let error = tokio::time::timeout(
            Duration::from_secs(1),
            poll_fn(|context| Pin::new(&mut connection).poll_write(context, b"second body")),
        )
        .await
        .expect("expected second write timeout before test timeout")
        .expect_err("expected second request write timeout");
        let timeout = request_write_timeout_from_error(&error)
            .expect("expected second request timeout context");
        assert_eq!(timeout.origin(), SECOND_ORIGIN);
        assert_eq!(timeout.redirect_hop(), 1);
    });
}

#[test]
fn stale_connection_abort_does_not_claim_the_current_use() {
    let metrics = Arc::new(Metrics::default());
    let telemetry = ConnectionTelemetry::new(Arc::clone(&metrics), None, IDLE_TIMEOUT);
    let stale_use = telemetry.request_started(None, None);
    let current_use = telemetry.request_started(None, None);

    stale_use.abort(ConnectionAbortReason::Error(None));
    assert_eq!(metrics.snapshot().connections_aborted, 0);

    current_use.abort(ConnectionAbortReason::Error(None));
    assert_eq!(metrics.snapshot().connections_aborted, 1);
}

#[test]
fn bodyless_reuse_does_not_inherit_completed_request_write_timeout() {
    runtime().block_on(async {
        let metrics = Arc::new(Metrics::default());
        let mut connection = pending_write_connection(metrics);
        let first_use = connection.telemetry.request_started(
            None,
            Some(RequestWriteTimeoutContext::new(
                WRITE_TIMEOUT,
                WRITE_TIMEOUT.as_secs_f64(),
                ORIGIN.to_owned(),
                0,
            )),
        );
        let waker = std::task::Waker::noop();
        let mut context = Context::from_waker(waker);
        assert!(Pin::new(&mut connection)
            .poll_write(&mut context, b"request body")
            .is_pending());
        first_use.finish(ResponseBodyLifecycleOutcome::Closed);
        let _bodyless_use = connection.telemetry.request_started(None, None);

        let result = tokio::time::timeout(
            WRITE_TIMEOUT * 2,
            poll_fn(|context| Pin::new(&mut connection).poll_write(context, b"headers")),
        )
        .await;

        assert!(
            result.is_err(),
            "bodyless request inherited a write timeout"
        );
    });
}

#[test]
fn connection_close_clears_active_request_write_timeout() {
    runtime().block_on(async {
        let metrics = Arc::new(Metrics::default());
        let mut connection = pending_write_connection(metrics);
        let _connection_use = connection.telemetry.request_started(
            None,
            Some(RequestWriteTimeoutContext::new(
                WRITE_TIMEOUT,
                WRITE_TIMEOUT.as_secs_f64(),
                ORIGIN.to_owned(),
                0,
            )),
        );
        let waker = Waker::noop();
        let mut context = Context::from_waker(waker);
        assert!(Pin::new(&mut connection)
            .poll_write(&mut context, b"request body")
            .is_pending());

        connection.telemetry.connection_closed();
        let result = tokio::time::timeout(
            WRITE_TIMEOUT * 2,
            poll_fn(|context| Pin::new(&mut connection).poll_write(context, b"request body")),
        )
        .await;

        assert!(
            result.is_err(),
            "closed connection retained its write timeout"
        );
    });
}

#[test]
fn closed_connection_rejects_late_request_write_timeout() {
    runtime().block_on(async {
        let metrics = Arc::new(Metrics::default());
        let mut connection = pending_write_connection(metrics);
        connection.telemetry.connection_closed();
        let _connection_use = connection.telemetry.request_started(
            None,
            Some(RequestWriteTimeoutContext::new(
                WRITE_TIMEOUT,
                WRITE_TIMEOUT.as_secs_f64(),
                ORIGIN.to_owned(),
                0,
            )),
        );

        let result = tokio::time::timeout(
            WRITE_TIMEOUT * 2,
            poll_fn(|context| Pin::new(&mut connection).poll_write(context, b"request body")),
        )
        .await;

        assert!(
            result.is_err(),
            "closed connection accepted a late write timeout"
        );
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
        _connection_permit: crate::core::client::connection_limit::ConnectionPermit::default(),
    }
}

struct FakeConnection {
    write_sequence: Vec<Poll<Result<usize, Error>>>,
    writes: Arc<Mutex<usize>>,
    shutdown_pending: bool,
    shutdowns: Arc<Mutex<usize>>,
}

#[derive(Default)]
struct WakeFlag(AtomicBool);

impl Wake for WakeFlag {
    fn wake(self: Arc<Self>) {
        self.0.store(true, Ordering::Release);
    }
}

impl FakeConnection {
    fn always_pending() -> Self {
        Self {
            write_sequence: Vec::new(),
            writes: Arc::new(Mutex::new(0)),
            shutdown_pending: false,
            shutdowns: Arc::new(Mutex::new(0)),
        }
    }

    fn with_write_sequence<const N: usize>(sequence: [Poll<Result<usize, Error>>; N]) -> Self {
        Self {
            write_sequence: Vec::from(sequence).into_iter().rev().collect(),
            writes: Arc::new(Mutex::new(0)),
            shutdown_pending: false,
            shutdowns: Arc::new(Mutex::new(0)),
        }
    }

    fn with_pending_shutdown() -> Self {
        Self {
            write_sequence: Vec::new(),
            writes: Arc::new(Mutex::new(0)),
            shutdown_pending: true,
            shutdowns: Arc::new(Mutex::new(0)),
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
        let connection = self.get_mut();
        *connection.shutdowns.lock().unwrap() += 1;
        if connection.shutdown_pending {
            Poll::Pending
        } else {
            Poll::Ready(Ok(()))
        }
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
