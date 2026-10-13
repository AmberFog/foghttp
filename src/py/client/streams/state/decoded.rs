use super::{StreamFinish, StreamReadGuard};
use crate::core::client::ConnectionAbortReason;
use crate::core::metrics::Metrics;
use crate::core::response::{StepStatus, StreamDecodeError, StreamingDecodePlan, StreamingDecoder};
use crate::core::telemetry::TelemetryErrorType;
use crate::errors::{
    FogHttpLifecycleError, FogHttpResponseBodyTooLargeError, FogHttpResponseDecodingError,
};
use crate::messages::STREAM_RESPONSE_READ_ABORTED;
use crate::py::client::streams::read::next_stream_body_frame;
use crate::py::client::streams::{StreamDecodeOptions, StreamDecoderReservation};
use crate::py::client::timeout_diagnostics::response_body_transport_error;
use bytes::{Buf, Bytes};
use hyper::body::Body;
use pyo3::prelude::*;
use std::sync::Arc;

pub(crate) struct DecodedStream {
    decoder: StreamingDecoder,
    input: Bytes,
    // Drop the decoder and its retained input before releasing admission capacity.
    _reservation: StreamDecoderReservation,
}

impl DecodedStream {
    pub(crate) fn new(
        plan: StreamingDecodePlan,
        options: StreamDecodeOptions,
        metrics: Arc<Metrics>,
    ) -> PyResult<Self> {
        let reservation = StreamDecoderReservation::try_new(
            plan.reservation_bytes(),
            options.max_memory_bytes,
            metrics,
        )?;
        Ok(Self {
            decoder: StreamingDecoder::new(plan, options.max_decoded_bytes),
            input: Bytes::new(),
            _reservation: reservation,
        })
    }
}

pub(crate) fn stream_decode_error(error: &StreamDecodeError) -> PyErr {
    match error {
        StreamDecodeError::TooLarge { .. } | StreamDecodeError::CounterOverflow => {
            FogHttpResponseBodyTooLargeError::new_err(error.to_string())
        }
        _ => FogHttpResponseDecodingError::new_err(error.to_string()),
    }
}

impl StreamReadGuard {
    pub(super) async fn read_decoded_chunk(mut self) -> PyResult<Option<Bytes>> {
        loop {
            self.ensure_decoded_read_open()?;
            // Incoming can establish clean HTTP EOF with the final data frame.
            // Finalizing content must not retain ownership of that connection.
            if self.body.as_ref().is_some_and(Body::is_end_stream) {
                self.finish_decoded_transport();
            }
            let eof = self.body.is_none();
            let decoded = self.decoded.as_mut().expect("decoded read owns decoder");
            let step = match decoded.decoder.step(&decoded.input, eof) {
                Ok(step) => step,
                Err(error) => {
                    let error_type = match error {
                        StreamDecodeError::TooLarge { .. } | StreamDecodeError::CounterOverflow => {
                            TelemetryErrorType::ResponseBodyTooLargeError
                        }
                        _ => TelemetryErrorType::ResponseDecodingError,
                    };
                    self.state
                        .abort_from_read(ConnectionAbortReason::Error(Some(error_type)));
                    return Err(stream_decode_error(&error));
                }
            };
            decoded.input.advance(step.consumed);
            if let Some(output) = step.output {
                self.finish_decoded_chunk()?;
                return Ok(Some(output));
            }
            match step.status {
                StepStatus::Finished => {
                    self.decoded.take();
                    if !self.state.finish(StreamFinish::Success, false) {
                        return Err(FogHttpLifecycleError::new_err(STREAM_RESPONSE_READ_ABORTED));
                    }
                    self.disarmed = true;
                    return Ok(None);
                }
                StepStatus::NeedsInput => self.refill_decoded_input().await?,
                StepStatus::Progress => tokio::task::yield_now().await,
            }
        }
    }

    async fn refill_decoded_input(&mut self) -> PyResult<()> {
        let timeout = self.read_timeout;
        let timeout_secs = self.read_timeout_secs;
        let origin = self.origin.clone();
        let hop = self.redirect_hop;
        let frame = next_stream_body_frame(self.body_mut(), timeout, timeout_secs, &origin, hop)
            .await
            .inspect_err(|_| {
                self.state
                    .abort_from_read(ConnectionAbortReason::Error(Some(
                        TelemetryErrorType::ReadTimeout,
                    )));
            })?;
        self.ensure_decoded_read_open()?;
        match frame {
            None => self.finish_decoded_transport(),
            Some(Err(error)) => {
                let write_timeout = self.state.request_write_timeout();
                let error_type = if write_timeout.is_some() {
                    TelemetryErrorType::WriteTimeout
                } else {
                    TelemetryErrorType::RequestError
                };
                self.state
                    .abort_from_read(ConnectionAbortReason::Error(Some(error_type)));
                return Err(response_body_transport_error(
                    write_timeout,
                    error.to_string(),
                ));
            }
            Some(Ok(frame)) => {
                if let Ok(data) = frame.into_data() {
                    let decoded = self.decoded.as_mut().expect("decoded read owns decoder");
                    debug_assert!(decoded.input.is_empty());
                    decoded.input = data;
                }
            }
        }
        Ok(())
    }

    fn finish_decoded_transport(&mut self) {
        self.body.take();
        self.state.finish_transport_from_read();
    }

    fn ensure_decoded_read_open(&self) -> PyResult<()> {
        if self.state.is_finished() {
            Err(FogHttpLifecycleError::new_err(STREAM_RESPONSE_READ_ABORTED))
        } else {
            Ok(())
        }
    }

    fn finish_decoded_chunk(mut self) -> PyResult<()> {
        let mut fields = self.state.fields();
        if fields.terminal.is_some() {
            return Err(FogHttpLifecycleError::new_err(STREAM_RESPONSE_READ_ABORTED));
        }
        fields.body = self.body.take();
        fields.decoded = self.decoded.take();
        self.disarmed = true;
        Ok(())
    }
}

#[cfg(test)]
mod tests;
