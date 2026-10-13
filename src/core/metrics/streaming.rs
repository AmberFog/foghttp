use super::Metrics;
use std::sync::atomic::Ordering;

impl Metrics {
    pub fn try_reserve_stream_decoder_bytes(&self, bytes: usize, max_bytes: usize) -> bool {
        self.stream_decoder_reserved_bytes
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |current| {
                current.checked_add(bytes).filter(|next| *next <= max_bytes)
            })
            .is_ok()
    }

    pub fn release_stream_decoder_bytes(&self, bytes: usize) {
        // Reservation ownership prevents double release; Drop must not wrap the gauge.
        let _ = self.stream_decoder_reserved_bytes.fetch_update(
            Ordering::AcqRel,
            Ordering::Acquire,
            |current| current.checked_sub(bytes),
        );
    }
}
