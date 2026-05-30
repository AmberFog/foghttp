use super::origin::OriginMetricsSnapshot;
use super::telemetry::TelemetrySnapshotMetadata;
use super::Metrics;

const TRANSPORT_STATE_SNAPSHOT_ATTEMPTS: usize = 8;

pub struct MetricsSnapshot {
    pub active_requests: usize,
    pub pending_requests: usize,
    pub peak_pending_requests: usize,
    pub total_requests: usize,
    pub failed_requests: usize,
    pub pool_acquire_attempts: usize,
    pub pool_acquire_immediate: usize,
    pub pool_acquire_waited: usize,
    pub pool_acquire_timeouts: usize,
    pub pool_acquire_wait_time_total_ns: u64,
    pub pool_acquire_wait_time_max_ns: u64,
    pub pool_acquire_wait_time_last_ns: u64,
    pub response_body_reuse_eligible: usize,
    pub response_body_closed: usize,
    pub response_body_aborted: usize,
    pub active_connections: usize,
    pub idle_connections: usize,
    pub connections_opened: usize,
    pub connections_open_failed: usize,
    pub connections_closed: usize,
    pub connections_reused: usize,
    pub connections_aborted: usize,
    pub buffered_response_bytes: usize,
    pub buffered_response_budget_rejections: usize,
}

pub struct StatsSnapshot {
    pub metadata: TelemetrySnapshotMetadata,
    pub metrics: MetricsSnapshot,
}

pub struct TransportStateSnapshot {
    pub metadata: TelemetrySnapshotMetadata,
    pub metrics: MetricsSnapshot,
    pub origins: Vec<OriginMetricsSnapshot>,
    pub(super) origins_include_all_historical_pressure: bool,
}

impl Metrics {
    pub fn transport_state_snapshot(&self) -> TransportStateSnapshot {
        let metadata = self.next_telemetry_snapshot_metadata();
        let mut snapshot = self.transport_state_snapshot_once(metadata);
        for _attempt in 1..TRANSPORT_STATE_SNAPSHOT_ATTEMPTS {
            if snapshot.has_coherent_pressure() {
                return snapshot;
            }

            std::hint::spin_loop();
            snapshot = self.transport_state_snapshot_once(metadata);
        }
        snapshot
    }

    pub(super) fn transport_state_snapshot_once(
        &self,
        metadata: TelemetrySnapshotMetadata,
    ) -> TransportStateSnapshot {
        TransportStateSnapshot {
            metadata,
            metrics: self.snapshot(),
            origins: self.origin_snapshots(),
            origins_include_all_historical_pressure: self
                .origin_registry
                .snapshots_include_all_historical_origins(),
        }
    }
}

impl TransportStateSnapshot {
    pub(super) fn has_coherent_pressure(&self) -> bool {
        let totals = OriginPressureTotals::from_origins(&self.origins);

        self.has_coherent_current_pressure(&totals)
            // Historical acquire counters can only be compared while the
            // per-origin registry still contains all origins ever observed.
            && (!self.origins_include_all_historical_pressure
                || self.has_coherent_historical_transport_counters(&totals))
    }

    fn has_coherent_current_pressure(&self, totals: &OriginPressureTotals) -> bool {
        self.metrics.active_requests == totals.active_requests
            && self.metrics.pending_requests == totals.pending_requests
            && self.metrics.active_connections == totals.active_connections
            && self.metrics.idle_connections == totals.idle_connections
    }

    fn has_coherent_historical_transport_counters(&self, totals: &OriginPressureTotals) -> bool {
        self.metrics.pool_acquire_attempts == totals.pool_acquire_attempts
            && self.metrics.pool_acquire_immediate == totals.pool_acquire_immediate
            && self.metrics.pool_acquire_waited == totals.pool_acquire_waited
            && self.metrics.pool_acquire_timeouts == totals.pool_acquire_timeouts
            && self.metrics.pool_acquire_wait_time_total_ns
                == totals.pool_acquire_wait_time_total_ns
            && self.metrics.pool_acquire_wait_time_max_ns == totals.pool_acquire_wait_time_max_ns
            && self.metrics.response_body_reuse_eligible == totals.response_body_reuse_eligible
            && self.metrics.response_body_closed == totals.response_body_closed
            && self.metrics.response_body_aborted == totals.response_body_aborted
            && self.metrics.connections_opened == totals.connections_opened
            && self.metrics.connections_open_failed == totals.connections_open_failed
            && self.metrics.connections_closed == totals.connections_closed
            && self.metrics.connections_reused == totals.connections_reused
            && self.metrics.connections_aborted == totals.connections_aborted
    }
}

#[derive(Default)]
struct OriginPressureTotals {
    active_requests: usize,
    pending_requests: usize,
    active_connections: usize,
    idle_connections: usize,
    pool_acquire_attempts: usize,
    pool_acquire_immediate: usize,
    pool_acquire_waited: usize,
    pool_acquire_timeouts: usize,
    pool_acquire_wait_time_total_ns: u64,
    pool_acquire_wait_time_max_ns: u64,
    response_body_reuse_eligible: usize,
    response_body_closed: usize,
    response_body_aborted: usize,
    connections_opened: usize,
    connections_open_failed: usize,
    connections_closed: usize,
    connections_reused: usize,
    connections_aborted: usize,
}

impl OriginPressureTotals {
    fn from_origins(origins: &[OriginMetricsSnapshot]) -> Self {
        origins.iter().fold(Self::default(), |mut totals, origin| {
            totals.active_requests = totals
                .active_requests
                .saturating_add(origin.active_requests);
            totals.pending_requests = totals
                .pending_requests
                .saturating_add(origin.pending_requests);
            totals.active_connections = totals
                .active_connections
                .saturating_add(origin.active_connections);
            totals.idle_connections = totals
                .idle_connections
                .saturating_add(origin.idle_connections);
            totals.pool_acquire_attempts = totals
                .pool_acquire_attempts
                .saturating_add(origin.pool_acquire_attempts);
            totals.pool_acquire_immediate = totals
                .pool_acquire_immediate
                .saturating_add(origin.pool_acquire_immediate);
            totals.pool_acquire_waited = totals
                .pool_acquire_waited
                .saturating_add(origin.pool_acquire_waited);
            totals.pool_acquire_timeouts = totals
                .pool_acquire_timeouts
                .saturating_add(origin.pool_acquire_timeouts);
            totals.pool_acquire_wait_time_total_ns = totals
                .pool_acquire_wait_time_total_ns
                .saturating_add(origin.pool_acquire_wait_time_total_ns);
            totals.pool_acquire_wait_time_max_ns = totals
                .pool_acquire_wait_time_max_ns
                .max(origin.pool_acquire_wait_time_max_ns);
            totals.response_body_reuse_eligible = totals
                .response_body_reuse_eligible
                .saturating_add(origin.response_body_reuse_eligible);
            totals.response_body_closed = totals
                .response_body_closed
                .saturating_add(origin.response_body_closed);
            totals.response_body_aborted = totals
                .response_body_aborted
                .saturating_add(origin.response_body_aborted);
            totals.connections_opened = totals
                .connections_opened
                .saturating_add(origin.connections_opened);
            totals.connections_open_failed = totals
                .connections_open_failed
                .saturating_add(origin.connections_open_failed);
            totals.connections_closed = totals
                .connections_closed
                .saturating_add(origin.connections_closed);
            totals.connections_reused = totals
                .connections_reused
                .saturating_add(origin.connections_reused);
            totals.connections_aborted = totals
                .connections_aborted
                .saturating_add(origin.connections_aborted);
            totals
        })
    }
}
