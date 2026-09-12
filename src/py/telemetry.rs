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
mod tests;
