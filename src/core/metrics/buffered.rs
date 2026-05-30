use super::Metrics;
use std::sync::atomic::Ordering;

#[derive(Debug, Eq, PartialEq)]
pub enum BufferedByteReservationError {
    CounterOverflow,
    LimitExceeded,
}

impl Metrics {
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
}
