use super::snapshots::StatsSnapshot;
use super::{Metrics, TELEMETRY_SNAPSHOT_SCHEMA_VERSION};
use std::sync::atomic::Ordering;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TelemetrySnapshotMetadata {
    pub schema_version: u64,
    pub snapshot_sequence: u64,
}

impl Metrics {
    pub fn stats_snapshot(&self) -> StatsSnapshot {
        StatsSnapshot {
            metadata: self.next_telemetry_snapshot_metadata(),
            metrics: self.snapshot(),
        }
    }

    pub fn next_telemetry_snapshot_metadata(&self) -> TelemetrySnapshotMetadata {
        TelemetrySnapshotMetadata {
            schema_version: TELEMETRY_SNAPSHOT_SCHEMA_VERSION,
            snapshot_sequence: self.next_telemetry_snapshot_sequence(),
        }
    }

    fn next_telemetry_snapshot_sequence(&self) -> u64 {
        // This counter only orders observations; it does not publish metrics state.
        let mut current = self.telemetry_snapshot_sequence.load(Ordering::Relaxed);
        loop {
            let Some(next) = current.checked_add(1) else {
                return u64::MAX;
            };

            match self.telemetry_snapshot_sequence.compare_exchange_weak(
                current,
                next,
                Ordering::Relaxed,
                Ordering::Relaxed,
            ) {
                Ok(_previous) => return next,
                Err(actual) => current = actual,
            }
        }
    }
}
