use super::RawTelemetryEvent;
use crate::core::telemetry::{
    TelemetryErrorType, TelemetryEventRecord, TelemetryEventType, TelemetryOutcome,
    TelemetryRequestMode,
};
use std::time::Duration;

#[test]
fn raw_event_preserves_typed_native_fields() {
    let raw = RawTelemetryEvent::from(TelemetryEventRecord {
        event_type: TelemetryEventType::PoolAcquireFinished,
        request_id: Some(7),
        mode: Some(TelemetryRequestMode::Buffered),
        method: Some("GET".to_owned()),
        origin: Some("https://example.com".to_owned()),
        elapsed: Some(Duration::from_millis(3)),
        redirect_hop: Some(1),
        outcome: Some(TelemetryOutcome::Error),
        error_type: Some(TelemetryErrorType::PoolTimeout),
    });

    assert_eq!(raw.event_type, "pool_acquire_finished");
    assert_eq!(raw.request_id, Some(7));
    assert_eq!(raw.mode.as_deref(), Some("buffered"));
    assert_eq!(raw.method.as_deref(), Some("GET"));
    assert_eq!(raw.origin.as_deref(), Some("https://example.com"));
    assert_eq!(raw.elapsed_ns, Some(3_000_000));
    assert_eq!(raw.redirect_hop, Some(1));
    assert_eq!(raw.outcome.as_deref(), Some("error"));
    assert_eq!(raw.error_type.as_deref(), Some("PoolTimeout"));
}
