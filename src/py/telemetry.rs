use crate::core::telemetry::{TelemetryEventBatch, TelemetryEventRecord};
use pyo3::prelude::*;

#[pyclass(skip_from_py_object)]
pub struct RawTelemetryEvent {
    #[pyo3(get)]
    event_type: String,
    #[pyo3(get)]
    request_id: Option<u64>,
    #[pyo3(get)]
    mode: Option<String>,
    #[pyo3(get)]
    method: Option<String>,
    #[pyo3(get)]
    origin: Option<String>,
    #[pyo3(get)]
    elapsed_ns: Option<u64>,
    #[pyo3(get)]
    redirect_hop: Option<usize>,
    #[pyo3(get)]
    outcome: Option<String>,
    #[pyo3(get)]
    error_type: Option<String>,
}

pub(crate) fn raw_telemetry_batch(batch: TelemetryEventBatch) -> (Vec<RawTelemetryEvent>, u64) {
    let events = batch.events.into_iter().map(Into::into).collect();
    (events, batch.dropped_events)
}

impl From<TelemetryEventRecord> for RawTelemetryEvent {
    fn from(event: TelemetryEventRecord) -> Self {
        Self {
            event_type: event.event_type.as_str().to_owned(),
            request_id: event.request_id,
            mode: event.mode.map(|mode| mode.as_str().to_owned()),
            method: event.method,
            origin: event.origin,
            elapsed_ns: event.elapsed.map(duration_as_nanos),
            redirect_hop: event.redirect_hop,
            outcome: event.outcome.map(|outcome| outcome.as_str().to_owned()),
            error_type: event
                .error_type
                .map(|error_type| error_type.as_str().to_owned()),
        }
    }
}

fn duration_as_nanos(duration: std::time::Duration) -> u64 {
    duration.as_nanos().try_into().unwrap_or(u64::MAX)
}

#[cfg(test)]
mod tests {
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
}
