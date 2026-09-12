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
mod tests {
    use super::{enforce_response_body_limit, BufferedBodyCollector, CollectedBody};
    use crate::core::metrics::Metrics;
    use crate::core::response::{BufferedBodyBudget, ResponseBodyError};
    use std::sync::Arc;

    #[test]
    fn body_limit_handles_exact_zero_overflow_and_unbounded_sizes() {
        assert!(enforce_response_body_limit(0, 0, Some(0)).is_ok());
        assert!(enforce_response_body_limit(3, 5, Some(8)).is_ok());
        assert!(enforce_response_body_limit(usize::MAX, 1, None).is_ok());
        for (current, chunk, limit) in [(0, 1, 0), (3, 6, 8), (usize::MAX, 1, usize::MAX)] {
            let error = enforce_response_body_limit(current, chunk, Some(limit)).unwrap_err();
            assert!(
                matches!(error, ResponseBodyError::TooLarge { limit: actual } if actual == limit)
            );
            assert_eq!(
                error.to_string(),
                crate::messages::response_body_too_large(limit)
            );
        }
    }

    #[test]
    fn rejected_chunk_preserves_collected_bytes_until_drop_releases_reservation() {
        let metrics = Arc::new(Metrics::default());
        let budget = BufferedBodyBudget::new(Some(8), Arc::clone(&metrics));
        let mut collector = BufferedBodyCollector {
            collected: CollectedBody {
                content: Vec::new(),
                reservation: budget.start_response(),
            },
            max_response_body_size: Some(3),
        };
        collector.push_data(b"abc").unwrap();
        assert!(matches!(
            collector.push_data(b"d"),
            Err(ResponseBodyError::TooLarge { limit: 3 })
        ));
        assert_eq!(collector.collected.content, b"abc");
        assert_eq!(metrics.snapshot().buffered_response_bytes, 3);
        assert_eq!(metrics.snapshot().buffered_response_budget_rejections, 0);
        drop(collector);
        assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
    }
}
