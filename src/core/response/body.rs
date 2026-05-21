use super::budget::{BufferedBodyBudget, BufferedBodyReservation};
use crate::errors::{FogHttpError, FogHttpResponseBodyTooLargeError};
use crate::messages::response_body_too_large;
use http_body_util::BodyExt;
use hyper::body::{Body, Incoming};
use pyo3::prelude::*;

pub struct CollectedBody {
    pub content: Vec<u8>,
    pub reservation: BufferedBodyReservation,
}

pub async fn collect_body(
    mut body: Incoming,
    max_response_body_size: Option<usize>,
    budget: BufferedBodyBudget,
) -> PyResult<CollectedBody> {
    let mut collected = CollectedBody {
        content: Vec::new(),
        reservation: budget.start_response(),
    };
    enforce_response_size_hint(&body, max_response_body_size)?;

    while let Some(frame) = body.frame().await {
        let frame = frame.map_err(|err| FogHttpError::new_err(err.to_string()))?;
        let Ok(data) = frame.into_data() else {
            continue;
        };

        enforce_response_body_limit(collected.content.len(), data.len(), max_response_body_size)?;
        collected.reservation.reserve_chunk(data.len())?;
        collected.content.extend_from_slice(&data);
    }

    Ok(collected)
}

fn enforce_response_size_hint(
    body: &Incoming,
    max_response_body_size: Option<usize>,
) -> PyResult<()> {
    let Some(limit) = max_response_body_size else {
        return Ok(());
    };
    let Some(upper_size_hint) = body.size_hint().upper() else {
        return Ok(());
    };
    let exceeds_limit = usize::try_from(upper_size_hint).map_or(true, |size| size > limit);
    if exceeds_limit {
        return Err(response_body_limit_error(limit));
    }

    Ok(())
}

pub(super) fn enforce_response_body_limit(
    current_size: usize,
    chunk_size: usize,
    max_response_body_size: Option<usize>,
) -> PyResult<()> {
    let Some(limit) = max_response_body_size else {
        return Ok(());
    };

    let Some(next_size) = current_size.checked_add(chunk_size) else {
        return Err(response_body_limit_error(limit));
    };
    if next_size > limit {
        return Err(response_body_limit_error(limit));
    }

    Ok(())
}

fn response_body_limit_error(limit: usize) -> PyErr {
    FogHttpResponseBodyTooLargeError::new_err(response_body_too_large(limit))
}
