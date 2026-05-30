use super::blocking::PendingRequestBlockingReason;
use crate::core::metrics::atomic::duration_as_nanos;
use std::collections::HashMap;
use std::time::Instant;

pub(super) struct PendingWaiters {
    next_waiter_id: u64,
    waiters: HashMap<u64, PendingWaiter>,
}

struct PendingWaiter {
    started: Instant,
    blocked_by: PendingRequestBlockingReason,
}

pub(super) struct PendingWaitersSnapshot {
    pub pending_requests: usize,
    pub oldest_pending_request_wait_ns: u64,
    pub blocked_by: PendingRequestBlockingReason,
}

impl Default for PendingWaiters {
    fn default() -> Self {
        Self {
            next_waiter_id: 1,
            waiters: HashMap::new(),
        }
    }
}

impl PendingWaiters {
    pub(super) fn insert(&mut self, blocked_by: PendingRequestBlockingReason) -> u64 {
        let waiter_id = self.next_waiter_id;
        self.next_waiter_id = self.next_waiter_id.saturating_add(1);
        self.waiters.insert(
            waiter_id,
            PendingWaiter {
                started: Instant::now(),
                blocked_by,
            },
        );
        waiter_id
    }

    pub(super) fn remove(&mut self, waiter_id: u64) {
        self.waiters.remove(&waiter_id);
    }

    pub(super) fn snapshot(&self) -> PendingWaitersSnapshot {
        let Some(first_waiter) = self.waiters.values().next() else {
            return PendingWaitersSnapshot {
                pending_requests: 0,
                oldest_pending_request_wait_ns: 0,
                blocked_by: PendingRequestBlockingReason::None,
            };
        };

        let mut oldest_pending_request_wait_ns = duration_as_nanos(first_waiter.started.elapsed());
        let blocked_by = first_waiter.blocked_by;
        let mut is_mixed = false;

        for waiter in self.waiters.values().skip(1) {
            oldest_pending_request_wait_ns =
                oldest_pending_request_wait_ns.max(duration_as_nanos(waiter.started.elapsed()));
            if waiter.blocked_by != blocked_by {
                is_mixed = true;
            }
        }

        PendingWaitersSnapshot {
            pending_requests: self.waiters.len(),
            oldest_pending_request_wait_ns,
            blocked_by: if is_mixed {
                PendingRequestBlockingReason::Mixed
            } else {
                blocked_by
            },
        }
    }
}
