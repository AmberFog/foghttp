use super::ResponseBodyError;
use crate::core::metrics::{BufferedByteReservationError, Metrics};
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

    fn reserve_bytes(&self, byte_count: usize) -> Result<(), ResponseBodyError> {
        match self
            .metrics
            .reserve_buffered_response_bytes(byte_count, self.max_buffered_response_bytes)
        {
            Ok(()) => Ok(()),
            Err(BufferedByteReservationError::LimitExceeded) => {
                self.metrics.buffered_response_budget_rejected();
                let limit = self.max_buffered_response_bytes.unwrap_or(0);
                Err(ResponseBodyError::BudgetExceeded { limit })
            }
            Err(BufferedByteReservationError::CounterOverflow) => {
                Err(ResponseBodyError::CounterOverflow)
            }
        }
    }

    fn release_bytes(&self, byte_count: usize) {
        self.metrics.release_buffered_response_bytes(byte_count);
    }
}

impl BufferedBodyReservation {
    pub fn reserve_chunk(&mut self, chunk_size: usize) -> Result<(), ResponseBodyError> {
        let Some(next_reserved_bytes) = self.reserved_bytes.checked_add(chunk_size) else {
            return Err(ResponseBodyError::ReservationOverflow);
        };

        self.budget.reserve_bytes(chunk_size)?;
        self.reserved_bytes = next_reserved_bytes;
        Ok(())
    }

    pub fn release_chunk(&mut self, chunk_size: usize) -> Result<(), ResponseBodyError> {
        if chunk_size == 0 {
            return Ok(());
        }

        let Some(next_reserved_bytes) = self.reserved_bytes.checked_sub(chunk_size) else {
            return Err(ResponseBodyError::ReservationUnderflow);
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
mod tests;
