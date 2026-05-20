use std::sync::atomic::{AtomicUsize, Ordering};

#[derive(Default)]
pub struct Metrics {
    active_requests: AtomicUsize,
    pending_requests: AtomicUsize,
    total_requests: AtomicUsize,
    failed_requests: AtomicUsize,
    pool_acquire_timeouts: AtomicUsize,
    buffered_response_bytes: AtomicUsize,
    buffered_response_budget_rejections: AtomicUsize,
}

#[derive(Debug, Eq, PartialEq)]
pub enum BufferedByteReservationError {
    CounterOverflow,
    LimitExceeded,
}

pub struct MetricsSnapshot {
    pub active_requests: usize,
    pub pending_requests: usize,
    pub total_requests: usize,
    pub failed_requests: usize,
    pub pool_acquire_timeouts: usize,
    pub buffered_response_bytes: usize,
    pub buffered_response_budget_rejections: usize,
}

impl Metrics {
    pub fn request_started(&self) {
        self.total_requests.fetch_add(1, Ordering::Relaxed);
    }

    pub fn request_finished(&self, failed: bool) {
        if failed {
            self.failed_requests.fetch_add(1, Ordering::Relaxed);
        }
    }

    pub fn active_request_started(&self) {
        self.active_requests.fetch_add(1, Ordering::Relaxed);
    }

    pub fn active_request_finished(&self) {
        self.active_requests.fetch_sub(1, Ordering::Relaxed);
    }

    pub fn pending_request_started(&self, max_pending_requests: usize) -> bool {
        let mut current = self.pending_requests.load(Ordering::Acquire);
        loop {
            if current >= max_pending_requests {
                return false;
            }

            match self.pending_requests.compare_exchange_weak(
                current,
                current + 1,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_previous) => return true,
                Err(actual) => current = actual,
            }
        }
    }

    pub fn pending_request_finished(&self) {
        self.pending_requests.fetch_sub(1, Ordering::AcqRel);
    }

    pub fn pool_acquire_timeout(&self) {
        self.pool_acquire_timeouts.fetch_add(1, Ordering::Relaxed);
    }

    pub fn reserve_buffered_response_bytes(
        &self,
        byte_count: usize,
        max_buffered_response_bytes: Option<usize>,
    ) -> Result<(), BufferedByteReservationError> {
        if byte_count == 0 {
            return Ok(());
        }

        let mut current = self.buffered_response_bytes.load(Ordering::Acquire);
        loop {
            let Some(next) = current.checked_add(byte_count) else {
                return Err(BufferedByteReservationError::CounterOverflow);
            };
            if max_buffered_response_bytes.is_some_and(|limit| next > limit) {
                return Err(BufferedByteReservationError::LimitExceeded);
            }

            match self.buffered_response_bytes.compare_exchange_weak(
                current,
                next,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_previous) => return Ok(()),
                Err(actual) => current = actual,
            }
        }
    }

    pub fn release_buffered_response_bytes(&self, byte_count: usize) {
        if byte_count == 0 {
            return;
        }

        let mut current = self.buffered_response_bytes.load(Ordering::Acquire);
        loop {
            let Some(next) = current.checked_sub(byte_count) else {
                // Reservation ownership should make double-release impossible,
                // but Drop paths must never wrap the public counter.
                return;
            };

            match self.buffered_response_bytes.compare_exchange_weak(
                current,
                next,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_previous) => return,
                Err(actual) => current = actual,
            }
        }
    }

    pub fn buffered_response_budget_rejected(&self) {
        self.buffered_response_budget_rejections
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn snapshot(&self) -> MetricsSnapshot {
        MetricsSnapshot {
            active_requests: self.active_requests.load(Ordering::Relaxed),
            pending_requests: self.pending_requests.load(Ordering::Acquire),
            total_requests: self.total_requests.load(Ordering::Relaxed),
            failed_requests: self.failed_requests.load(Ordering::Relaxed),
            pool_acquire_timeouts: self.pool_acquire_timeouts.load(Ordering::Relaxed),
            buffered_response_bytes: self.buffered_response_bytes.load(Ordering::Acquire),
            buffered_response_budget_rejections: self
                .buffered_response_budget_rejections
                .load(Ordering::Relaxed),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{BufferedByteReservationError, Metrics};

    #[test]
    fn buffered_response_reservation_rejects_without_changing_reserved_bytes() {
        let metrics = Metrics::default();

        assert_eq!(metrics.reserve_buffered_response_bytes(8, Some(8)), Ok(()));
        assert_eq!(
            metrics.reserve_buffered_response_bytes(1, Some(8)),
            Err(BufferedByteReservationError::LimitExceeded)
        );

        assert_eq!(metrics.snapshot().buffered_response_bytes, 8);
    }

    #[test]
    fn buffered_response_release_does_not_underflow_reserved_bytes() {
        let metrics = Metrics::default();

        metrics.release_buffered_response_bytes(8);

        assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
    }
}
