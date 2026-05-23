use super::budget::{BufferedBodyBudget, BufferedBodyReservation};
use crate::errors::FogHttpResponseBodyTooLargeError;
use crate::messages::response_body_too_large;
use hyper::body::{Body, Incoming};
use pyo3::prelude::*;

pub struct CollectedBody {
    pub content: Vec<u8>,
    pub reservation: BufferedBodyReservation,
}

pub struct BufferedBodyCollector {
    collected: CollectedBody,
    max_response_body_size: Option<usize>,
}

impl BufferedBodyCollector {
    pub fn new(
        body: &Incoming,
        max_response_body_size: Option<usize>,
        budget: &BufferedBodyBudget,
    ) -> PyResult<Self> {
        enforce_response_size_hint(body, max_response_body_size)?;

        Ok(Self {
            collected: CollectedBody {
                content: Vec::new(),
                reservation: budget.start_response(),
            },
            max_response_body_size,
        })
    }

    pub fn push_data(&mut self, data: &[u8]) -> PyResult<()> {
        enforce_response_body_limit(
            self.collected.content.len(),
            data.len(),
            self.max_response_body_size,
        )?;
        self.collected.reservation.reserve_chunk(data.len())?;
        self.collected.content.extend_from_slice(data);
        Ok(())
    }

    pub fn finish(self) -> CollectedBody {
        self.collected
    }
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
