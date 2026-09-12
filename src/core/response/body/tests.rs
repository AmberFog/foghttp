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
        assert!(matches!(error, ResponseBodyError::TooLarge { limit: actual } if actual == limit));
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

#[test]
fn budget_rejection_preserves_collected_bytes_and_other_response_reservations() {
    let metrics = Arc::new(Metrics::default());
    let budget = BufferedBodyBudget::new(Some(8), Arc::clone(&metrics));
    let mut other_response = budget.start_response();
    other_response.reserve_chunk(5).unwrap();
    let mut collector = BufferedBodyCollector {
        collected: CollectedBody {
            content: Vec::new(),
            reservation: budget.start_response(),
        },
        max_response_body_size: Some(8),
    };

    collector.push_data(b"abc").unwrap();
    assert!(matches!(
        collector.push_data(b"de"),
        Err(ResponseBodyError::BudgetExceeded { limit: 8 })
    ));
    assert_eq!(collector.collected.content, b"abc");
    assert_eq!(metrics.snapshot().buffered_response_bytes, 8);
    assert_eq!(metrics.snapshot().buffered_response_budget_rejections, 1);

    drop(collector);
    assert_eq!(metrics.snapshot().buffered_response_bytes, 5);
    drop(other_response);
    assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
}

#[test]
fn finished_collector_keeps_its_reservation_until_the_result_is_dropped() {
    let metrics = Arc::new(Metrics::default());
    let budget = BufferedBodyBudget::new(Some(8), Arc::clone(&metrics));
    let mut collector = BufferedBodyCollector {
        collected: CollectedBody {
            content: Vec::new(),
            reservation: budget.start_response(),
        },
        max_response_body_size: Some(8),
    };

    collector.push_data(b"ab").unwrap();
    collector.push_data(b"cde").unwrap();
    let collected = collector.finish();
    assert_eq!(collected.content, b"abcde");
    assert_eq!(metrics.snapshot().buffered_response_bytes, 5);
    assert_eq!(metrics.snapshot().buffered_response_budget_rejections, 0);

    drop(collected);
    assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
    let mut next_response = budget.start_response();
    next_response.reserve_chunk(8).unwrap();
    assert_eq!(metrics.snapshot().buffered_response_bytes, 8);
    drop(next_response);
    assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
}
