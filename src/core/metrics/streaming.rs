use super::Metrics;
use std::sync::atomic::Ordering;

impl Metrics {
    pub fn try_reserve_stream_decoder_bytes(&self, bytes: usize, max_bytes: usize) -> bool {
        let mut current = self.stream_decoder_reserved_bytes.load(Ordering::Acquire);
        loop {
            let Some(next) = current.checked_add(bytes).filter(|next| *next <= max_bytes) else {
                return false;
            };
            match self.stream_decoder_reserved_bytes.compare_exchange_weak(
                current,
                next,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => return true,
                Err(actual) => current = actual,
            }
        }
    }

    pub fn release_stream_decoder_bytes(&self, bytes: usize) {
        // Reservation ownership prevents double release; Drop must not wrap the gauge.
        let mut current = self.stream_decoder_reserved_bytes.load(Ordering::Acquire);
        loop {
            let Some(next) = current.checked_sub(bytes) else {
                return;
            };
            match self.stream_decoder_reserved_bytes.compare_exchange_weak(
                current,
                next,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => return,
                Err(actual) => current = actual,
            }
        }
    }
}
