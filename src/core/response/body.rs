use super::budget::{BufferedBodyBudget, BufferedBodyReservation};
use super::ResponseBodyError;
use hyper::body::{Body, Incoming};

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
    ) -> Result<Self, ResponseBodyError> {
        enforce_response_size_hint(body, max_response_body_size)?;

        Ok(Self {
            collected: CollectedBody {
                content: Vec::new(),
                reservation: budget.start_response(),
            },
            max_response_body_size,
        })
    }

    pub fn push_data(&mut self, data: &[u8]) -> Result<(), ResponseBodyError> {
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
) -> Result<(), ResponseBodyError> {
    let Some(limit) = max_response_body_size else {
        return Ok(());
    };
    let Some(upper_size_hint) = body.size_hint().upper() else {
        return Ok(());
    };
    let exceeds_limit = usize::try_from(upper_size_hint).map_or(true, |size| size > limit);
    if exceeds_limit {
        return Err(ResponseBodyError::TooLarge { limit });
    }

    Ok(())
}

pub(super) fn enforce_response_body_limit(
    current_size: usize,
    chunk_size: usize,
    max_response_body_size: Option<usize>,
) -> Result<(), ResponseBodyError> {
    let Some(limit) = max_response_body_size else {
        return Ok(());
    };

    let Some(next_size) = current_size.checked_add(chunk_size) else {
        return Err(ResponseBodyError::TooLarge { limit });
    };
    if next_size > limit {
        return Err(ResponseBodyError::TooLarge { limit });
    }

    Ok(())
}

#[cfg(test)]
mod tests;
