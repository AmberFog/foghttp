use crate::core::metrics::{BufferedByteReservationError, Metrics};
use crate::errors::{FogHttpError, FogHttpResponseBodyBudgetExceededError};
use crate::messages::buffered_response_body_budget_exceeded;
use pyo3::prelude::*;
use std::sync::Arc;

#[derive(Clone)]
pub struct BufferedBodyBudget {
    max_buffered_response_bytes: Option<usize>,
    metrics: Arc<Metrics>,
}

pub struct BufferedBodyReservation {
    budget: BufferedBodyBudget,
    reserved_bytes: usize,
}

impl BufferedBodyBudget {
    pub fn new(max_buffered_response_bytes: Option<usize>, metrics: Arc<Metrics>) -> Self {
        Self {
            max_buffered_response_bytes,
            metrics,
        }
    }

    pub fn start_response(&self) -> BufferedBodyReservation {
        BufferedBodyReservation {
            budget: self.clone(),
            reserved_bytes: 0,
        }
    }

    fn reserve_bytes(&self, byte_count: usize) -> PyResult<()> {
        match self
            .metrics
            .reserve_buffered_response_bytes(byte_count, self.max_buffered_response_bytes)
        {
            Ok(()) => Ok(()),
            Err(BufferedByteReservationError::LimitExceeded) => {
                self.metrics.buffered_response_budget_rejected();
                let limit = self.max_buffered_response_bytes.unwrap_or(0);
                Err(FogHttpResponseBodyBudgetExceededError::new_err(
                    buffered_response_body_budget_exceeded(limit),
                ))
            }
            Err(BufferedByteReservationError::CounterOverflow) => Err(FogHttpError::new_err(
                "buffered response byte counter overflow",
            )),
        }
    }

    fn release_bytes(&self, byte_count: usize) {
        self.metrics.release_buffered_response_bytes(byte_count);
    }
}

impl BufferedBodyReservation {
    pub fn reserve_chunk(&mut self, chunk_size: usize) -> PyResult<()> {
        let Some(next_reserved_bytes) = self.reserved_bytes.checked_add(chunk_size) else {
            return Err(FogHttpError::new_err(
                "buffered response byte reservation overflow",
            ));
        };

        self.budget.reserve_bytes(chunk_size)?;
        self.reserved_bytes = next_reserved_bytes;
        Ok(())
    }

    pub fn release_chunk(&mut self, chunk_size: usize) -> PyResult<()> {
        if chunk_size == 0 {
            return Ok(());
        }

        let Some(next_reserved_bytes) = self.reserved_bytes.checked_sub(chunk_size) else {
            return Err(FogHttpError::new_err(
                "buffered response byte reservation underflow",
            ));
        };

        self.budget.release_bytes(chunk_size);
        self.reserved_bytes = next_reserved_bytes;
        Ok(())
    }
}

impl Drop for BufferedBodyReservation {
    fn drop(&mut self) {
        self.budget.release_bytes(self.reserved_bytes);
    }
}

#[cfg(test)]
mod tests {
    use super::BufferedBodyBudget;
    use crate::core::metrics::Metrics;
    use std::sync::Arc;

    #[test]
    fn release_chunk_releases_owned_buffered_bytes() {
        let metrics = Arc::new(Metrics::default());
        let budget = BufferedBodyBudget::new(None, Arc::clone(&metrics));
        let mut reservation = budget.start_response();

        reservation.reserve_chunk(8).unwrap();
        reservation.release_chunk(3).unwrap();

        assert_eq!(metrics.snapshot().buffered_response_bytes, 5);
    }

    #[test]
    fn release_chunk_rejects_reservation_underflow() {
        let metrics = Arc::new(Metrics::default());
        let budget = BufferedBodyBudget::new(None, Arc::clone(&metrics));
        let mut reservation = budget.start_response();

        reservation.reserve_chunk(8).unwrap();
        assert!(reservation.release_chunk(9).is_err());
        assert_eq!(metrics.snapshot().buffered_response_bytes, 8);

        drop(reservation);
        assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
    }
}
