use super::{
    ClientTelemetry, TelemetryErrorType, TelemetryEventRecord, TelemetryEventType,
    TelemetryOutcome, TelemetryRequestMode,
};
use std::sync::atomic::Ordering;
use std::sync::mpsc::channel;
use std::thread;

const ORIGIN: &str = "https://example.com";

#[test]
fn journal_is_bounded_and_reports_drops_once() {
    let telemetry = ClientTelemetry::with_capacity(1);
    let request = telemetry.request(1, TelemetryRequestMode::Buffered, "GET".to_owned());

    request.begin_pool_acquire(ORIGIN, 0);
    request.finish_pool_acquire_success();

    let first = telemetry.drain(None);
    assert_eq!(first.events.len(), 1);
    assert_eq!(first.dropped_events, 1);
    assert_eq!(telemetry.drain(None).dropped_events, 0);
}

#[test]
fn cancellation_finishes_active_pool_phase_once() {
    let telemetry = ClientTelemetry::with_capacity(4);
    let request = telemetry.request(7, TelemetryRequestMode::Stream, "GET".to_owned());

    request.begin_pool_acquire(ORIGIN, 2);
    request.cancel();
    request.finish_pool_acquire_error(TelemetryErrorType::PoolTimeout);

    let batch = telemetry.drain(Some(7));
    assert_eq!(batch.dropped_events, 0);
    assert_eq!(batch.events.len(), 2);
    assert_eq!(
        batch.events[0].event_type,
        TelemetryEventType::PoolAcquireStarted
    );
    assert_eq!(batch.events[0].outcome, None);
    assert_eq!(
        batch.events[1].event_type,
        TelemetryEventType::PoolAcquireFinished
    );
    assert_eq!(batch.events[1].outcome, Some(TelemetryOutcome::Cancelled));
    assert_eq!(
        batch.events[1].error_type,
        Some(TelemetryErrorType::CancelledError)
    );
}

#[test]
fn cancellation_prevents_a_late_phase_from_starting() {
    let telemetry = ClientTelemetry::with_capacity(2);
    let request = telemetry.request(7, TelemetryRequestMode::Buffered, "GET".to_owned());

    request.cancel();
    request.begin_pool_acquire(ORIGIN, 0);
    request.finish_pool_acquire_success();

    let batch = telemetry.drain(Some(7));
    assert!(batch.events.is_empty());
    assert_eq!(batch.dropped_events, 0);
}

#[test]
fn cancellation_finishes_active_connection_use_before_drain() {
    let telemetry = ClientTelemetry::with_capacity(2);
    let request = telemetry.request(7, TelemetryRequestMode::Buffered, "GET".to_owned());
    let connection_use = request
        .begin_connection_use(ORIGIN, false)
        .expect("connection use starts before cancellation");

    request.cancel();
    assert!(!connection_use.abort(
        TelemetryOutcome::Error,
        Some(TelemetryErrorType::ReadTimeout),
    ));

    let batch = telemetry.drain(Some(7));
    assert_eq!(batch.events.len(), 1);
    assert_eq!(
        batch.events[0].event_type,
        TelemetryEventType::ConnectionAborted
    );
    assert_eq!(batch.events[0].outcome, Some(TelemetryOutcome::Cancelled));
    assert_eq!(
        batch.events[0].error_type,
        Some(TelemetryErrorType::CancelledError),
    );
}

#[test]
fn connection_use_started_after_cancellation_cannot_emit_reuse_or_abort() {
    let telemetry = ClientTelemetry::with_capacity(1);
    let request = telemetry.request(7, TelemetryRequestMode::Buffered, "GET".to_owned());

    request.cancel();
    assert!(request.begin_connection_use(ORIGIN, true).is_none());

    assert!(telemetry.drain(Some(7)).events.is_empty());
}

#[test]
fn cancellation_claims_connection_use_after_an_in_flight_assignment() {
    let telemetry = ClientTelemetry::with_capacity(1);
    let request = telemetry.request(7, TelemetryRequestMode::Buffered, "GET".to_owned());
    let assignment = request.lock_connection_assignment();
    let cancelling_request = request.clone();
    let (waiting_sender, waiting_receiver) = channel();
    let cancellation = thread::spawn(move || {
        assert!(cancelling_request.connection_assignment.try_lock().is_err());
        waiting_sender
            .send(())
            .expect("assignment wait signal remains connected");
        cancelling_request.cancel();
    });
    waiting_receiver
        .recv()
        .expect("cancellation reached the assignment transition");

    let connection_use = request
        .begin_connection_use(ORIGIN, false)
        .expect("assignment started before cancellation");
    drop(assignment);
    cancellation.join().expect("cancellation thread");

    assert!(!connection_use.finish());
    let batch = telemetry.drain(Some(7));
    assert_eq!(batch.events.len(), 1);
    assert_eq!(
        batch.events[0].event_type,
        TelemetryEventType::ConnectionAborted
    );
    assert_eq!(batch.events[0].outcome, Some(TelemetryOutcome::Cancelled));
}

#[test]
fn completed_connection_use_is_not_reclassified_by_late_cancellation() {
    let telemetry = ClientTelemetry::with_capacity(1);
    let request = telemetry.request(7, TelemetryRequestMode::Buffered, "GET".to_owned());
    let connection_use = request
        .begin_connection_use(ORIGIN, false)
        .expect("connection use starts before completion");

    assert!(connection_use.finish());
    request.cancel();

    assert!(telemetry.drain(Some(7)).events.is_empty());
}

#[test]
fn connection_close_is_client_scoped() {
    let telemetry = ClientTelemetry::with_capacity(2);

    telemetry
        .connection_open(Some(ORIGIN.to_owned()), None)
        .opened()
        .expect("connection telemetry remains open")
        .closed();

    let event = telemetry
        .drain(None)
        .events
        .into_iter()
        .find(|event| event.event_type == TelemetryEventType::ConnectionClosed)
        .expect("connection close event");
    assert_eq!(event.event_type, TelemetryEventType::ConnectionClosed);
    assert_eq!(event.request_id, None);
    assert_eq!(event.mode, None);
    assert_eq!(event.method, None);
    assert_eq!(event.origin.as_deref(), Some(ORIGIN));
    assert_eq!(event.outcome, Some(TelemetryOutcome::Closed));
}

#[test]
fn client_shutdown_closes_registered_connections_once() {
    let telemetry = ClientTelemetry::with_capacity(4);
    let first = telemetry
        .connection_open(Some(ORIGIN.to_owned()), None)
        .opened()
        .expect("first connection telemetry");
    let second = telemetry
        .connection_open(Some(ORIGIN.to_owned()), None)
        .opened()
        .expect("second connection telemetry");

    telemetry.close_connections();
    first.closed();
    second.closed();

    let batch = telemetry.drain(None);
    assert_eq!(batch.events.len(), 4);
    assert_eq!(
        batch
            .events
            .iter()
            .filter(|event| event.event_type == TelemetryEventType::ConnectionClosed)
            .count(),
        2
    );
}

#[test]
fn client_shutdown_finishes_pending_connection_open_once() {
    let telemetry = ClientTelemetry::with_capacity(2);
    let request = telemetry.request(7, TelemetryRequestMode::Buffered, "GET".to_owned());
    let pending_open = telemetry.connection_open(Some(ORIGIN.to_owned()), Some(request.clone()));

    request.cancel();
    request.finish_active_phase_error(TelemetryErrorType::TimeoutError);
    telemetry.close_connections();
    drop(pending_open);

    let batch = telemetry.drain(None);
    assert_eq!(batch.events.len(), 1);
    assert_eq!(
        batch.events[0].event_type,
        TelemetryEventType::ConnectionOpenFailed
    );
    assert_eq!(batch.events[0].outcome, Some(TelemetryOutcome::Cancelled));
    assert_eq!(
        batch.events[0].error_type,
        Some(TelemetryErrorType::CancelledError)
    );
}

#[test]
fn connection_open_failure_before_shutdown_is_not_duplicated() {
    let telemetry = ClientTelemetry::with_capacity(2);

    telemetry
        .connection_open(Some(ORIGIN.to_owned()), None)
        .failed(TelemetryErrorType::NetworkError);
    telemetry.close_connections();

    let batch = telemetry.drain(None);
    assert_eq!(batch.events.len(), 1);
    assert_eq!(
        batch.events[0].event_type,
        TelemetryEventType::ConnectionOpenFailed
    );
    assert_eq!(batch.events[0].outcome, Some(TelemetryOutcome::Error));
    assert_eq!(
        batch.events[0].error_type,
        Some(TelemetryErrorType::NetworkError)
    );
}

#[test]
fn request_drain_claims_client_scoped_records_and_retains_foreign_requests() {
    let telemetry = ClientTelemetry::with_capacity(4);
    let first = telemetry.request(1, TelemetryRequestMode::Buffered, "GET".to_owned());
    let second = telemetry.request(2, TelemetryRequestMode::Stream, "POST".to_owned());

    let connection = telemetry
        .connection_open(Some(ORIGIN.to_owned()), None)
        .opened()
        .expect("connection telemetry");
    let _ = telemetry.drain(None);
    connection.closed();
    first.begin_pool_acquire(ORIGIN, 0);
    second.begin_pool_acquire(ORIGIN, 0);

    let first_batch = telemetry.drain(Some(1));
    assert_eq!(first_batch.events.len(), 2);
    assert!(first_batch
        .events
        .iter()
        .any(|event| event.request_id == Some(1)));
    assert!(first_batch
        .events
        .iter()
        .any(|event| event.request_id.is_none()));
    assert_eq!(first_batch.dropped_events, 0);

    let second_batch = telemetry.drain(Some(2));
    assert_eq!(second_batch.events.len(), 1);
    assert_eq!(second_batch.events[0].request_id, Some(2));
    assert_eq!(second_batch.dropped_events, 0);

    let client_batch = telemetry.drain(None);
    assert!(client_batch.events.is_empty());
}

#[test]
fn claimed_client_records_cannot_starve_later_request_events() {
    let telemetry = ClientTelemetry::with_capacity(2);
    let first = telemetry.request(1, TelemetryRequestMode::Buffered, "GET".to_owned());
    let second = telemetry.request(2, TelemetryRequestMode::Buffered, "GET".to_owned());

    let connection = telemetry
        .connection_open(Some(ORIGIN.to_owned()), None)
        .opened()
        .expect("connection telemetry");
    let _ = telemetry.drain(None);
    connection.closed();
    first.begin_pool_acquire(ORIGIN, 0);
    let first_batch = telemetry.drain(Some(1));
    assert_eq!(first_batch.events.len(), 2);
    assert!(first_batch
        .events
        .iter()
        .any(|event| event.event_type == TelemetryEventType::ConnectionClosed));

    second.begin_pool_acquire(ORIGIN, 0);
    second.finish_pool_acquire_success();

    assert_eq!(telemetry.drain(Some(2)).events.len(), 2);
    let final_batch = telemetry.drain(None);
    assert!(final_batch.events.is_empty());
    assert_eq!(final_batch.dropped_events, 0);
}

#[test]
fn shutdown_waits_for_in_flight_producers_and_rejects_late_records() {
    let telemetry = ClientTelemetry::with_capacity(2);
    let producer = telemetry
        .try_begin_production()
        .expect("producer starts before shutdown");
    let closing_telemetry = telemetry.clone();
    let close = thread::spawn(move || closing_telemetry.close_connections());

    while !telemetry.inner.closed.load(Ordering::Acquire) {
        thread::yield_now();
    }
    telemetry.record_unchecked(TelemetryEventRecord {
        event_type: TelemetryEventType::PoolAcquireStarted,
        request_id: Some(1),
        mode: Some(TelemetryRequestMode::Buffered),
        method: Some("GET".to_owned()),
        origin: Some(ORIGIN.to_owned()),
        elapsed: None,
        redirect_hop: Some(0),
        outcome: None,
        error_type: None,
    });
    drop(producer);
    close.join().expect("telemetry shutdown thread");

    assert_eq!(telemetry.drain(None).events.len(), 1);
    telemetry
        .request(2, TelemetryRequestMode::Buffered, "GET".to_owned())
        .begin_pool_acquire(ORIGIN, 0);
    assert!(telemetry.drain(None).events.is_empty());
}
