use super::context::RawResponseContext;
use super::errors::response_body_error;
use crate::core::response::{
    BufferedBodyDecoder, BufferedDecodeStatus, CollectedBody, ResponseBody,
    ResponseBodyDecodingPlan,
};
use crate::messages::REQUEST_TOTAL_TIMEOUT;
use crate::py::client::timeout_diagnostics::{
    remaining_duration, timeout_error, TimeoutContext, TimeoutPhase,
};
use pyo3::prelude::*;

pub(super) async fn decode_response_body(
    collected: CollectedBody,
    plan: ResponseBodyDecodingPlan,
    context: &RawResponseContext<'_>,
) -> PyResult<ResponseBody> {
    let decoding = plan.is_decoding();
    // Admit before constructing codecs; on cancellation drop decoder memory
    // before releasing the slot to another response on this runtime.
    let _permit = if decoding {
        ensure_decode_deadline(context)?;
        let total = decode_timeout_context(context);
        let remaining = remaining_duration("Timeouts.total", &total)?;
        Some(
            tokio::time::timeout(remaining, context.buffered_decoders.acquire())
                .await
                .map_err(|_| timeout_error(&total, REQUEST_TOTAL_TIMEOUT))?
                .expect("runtime decoder admission is never closed"),
        )
    } else {
        None
    };
    let mut decoder = BufferedBodyDecoder::new(collected, plan, context.max_response_body_size);
    if !decoding {
        return decoder
            .finish()
            .map_err(|error| response_body_error(&error));
    }

    loop {
        ensure_decode_deadline(context)?;
        let step = decoder.step();
        #[cfg(test)]
        if let (Some(checkpoint), Ok(status)) = (context.decode_checkpoint, step.as_ref()) {
            checkpoint
                .after_step(decoder.test_progress(), *status)
                .await;
        }
        ensure_decode_deadline(context)?;
        let status = step.map_err(|error| response_body_error(&error))?;
        tokio::task::yield_now().await;
        ensure_decode_deadline(context)?;
        if status == BufferedDecodeStatus::Finished {
            let body = decoder
                .finish()
                .map_err(|error| response_body_error(&error))?;
            ensure_decode_deadline(context)?;
            return Ok(body);
        }
    }
}

pub(super) fn ensure_decode_deadline(context: &RawResponseContext<'_>) -> PyResult<()> {
    let total = decode_timeout_context(context);
    if remaining_duration("Timeouts.total", &total)?.is_zero() {
        return Err(timeout_error(&total, REQUEST_TOTAL_TIMEOUT));
    }
    Ok(())
}

fn decode_timeout_context<'a>(context: &RawResponseContext<'a>) -> TimeoutContext<'a> {
    TimeoutContext::new(
        TimeoutPhase::ResponseBody,
        context.started,
        context.total_timeout,
        context.origin,
        context.redirect_hop,
    )
}

#[cfg(test)]
pub(super) mod test_control;

#[cfg(test)]
mod tests;
