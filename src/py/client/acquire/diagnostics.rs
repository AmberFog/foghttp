use crate::core::metrics::{
    MetricsSnapshot, OriginPoolDiagnosticsSnapshot, PendingRequestBlockingReason,
    TelemetrySnapshotMetadata,
};

pub struct PoolDiagnosticsSnapshot {
    pub metadata: TelemetrySnapshotMetadata,
    pub active_requests: usize,
    pub pending_requests: usize,
    pub pool_acquire_timeouts: usize,
    pub max_active_requests: usize,
    pub max_active_requests_per_origin: Option<usize>,
    pub max_pending_requests: usize,
    pub pending_queue_full: bool,
    pub oldest_pending_request_wait_ns: u64,
    pub blocked_by: PendingRequestBlockingReason,
    pub origins: Vec<OriginPoolDiagnosticsSnapshot>,
}

impl PoolDiagnosticsSnapshot {
    pub fn new(
        metadata: TelemetrySnapshotMetadata,
        metrics: &MetricsSnapshot,
        origins: Vec<OriginPoolDiagnosticsSnapshot>,
        max_active_requests: usize,
        max_active_requests_per_origin: Option<usize>,
        max_pending_requests: usize,
    ) -> Self {
        let mut pending_requests = 0;
        let mut oldest_pending_request_wait_ns = 0;
        let mut blocked_by = PendingRequestBlockingReason::None;
        for origin in &origins {
            pending_requests += origin.pending_requests;
            if origin.pending_requests == 0 {
                continue;
            }

            oldest_pending_request_wait_ns =
                oldest_pending_request_wait_ns.max(origin.oldest_pending_request_wait_ns);
            blocked_by = merge_blocking_reason(blocked_by, origin.blocked_by);
        }

        Self {
            metadata,
            active_requests: metrics.active_requests,
            pending_requests,
            pool_acquire_timeouts: metrics.pool_acquire_timeouts,
            max_active_requests,
            max_active_requests_per_origin,
            max_pending_requests,
            pending_queue_full: pending_requests >= max_pending_requests,
            oldest_pending_request_wait_ns,
            blocked_by,
            origins,
        }
    }
}

pub fn blocking_reason_name(reason: PendingRequestBlockingReason) -> &'static str {
    match reason {
        PendingRequestBlockingReason::None => "none",
        PendingRequestBlockingReason::GlobalActiveRequests => "global_active_requests",
        PendingRequestBlockingReason::PerOriginActiveRequests => "per_origin_active_requests",
        PendingRequestBlockingReason::Mixed => "mixed",
    }
}

fn merge_blocking_reason(
    current: PendingRequestBlockingReason,
    next: PendingRequestBlockingReason,
) -> PendingRequestBlockingReason {
    match (current, next) {
        (PendingRequestBlockingReason::None, reason)
        | (reason, PendingRequestBlockingReason::None) => reason,
        (left, right) if left == right => left,
        _mixed => PendingRequestBlockingReason::Mixed,
    }
}
