use crate::core::metrics::Metrics;
use crate::errors::FogHttpResponseBodyBudgetExceededError;
use pyo3::prelude::*;
use std::sync::Arc;

#[derive(Clone, Copy)]
pub struct StreamDecodeOptions {
    pub decode_content: bool,
    pub max_decoded_bytes: Option<usize>,
    pub max_memory_bytes: usize,
}

pub struct StreamDecoderReservation {
    bytes: usize,
    metrics: Arc<Metrics>,
}

impl StreamDecoderReservation {
    pub fn try_new(bytes: usize, max_bytes: usize, metrics: Arc<Metrics>) -> PyResult<Self> {
        if !metrics.try_reserve_stream_decoder_bytes(bytes, max_bytes) {
            return Err(FogHttpResponseBodyBudgetExceededError::new_err(format!(
                "Stream decoder reservation exceeds max_stream_decoder_memory_bytes={max_bytes}"
            )));
        }
        Ok(Self { bytes, metrics })
    }
}

impl Drop for StreamDecoderReservation {
    fn drop(&mut self) {
        self.metrics.release_stream_decoder_bytes(self.bytes);
    }
}
