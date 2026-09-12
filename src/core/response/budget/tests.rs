use super::BufferedBodyBudget;
use crate::core::metrics::Metrics;
use crate::core::response::ResponseBodyError;
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
    assert!(matches!(
        reservation.release_chunk(9),
        Err(ResponseBodyError::ReservationUnderflow)
    ));
    assert_eq!(metrics.snapshot().buffered_response_bytes, 8);

    drop(reservation);
    assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
}

#[test]
fn rejected_budget_reservation_does_not_change_owned_bytes() {
    let metrics = Arc::new(Metrics::default());
    let budget = BufferedBodyBudget::new(Some(8), Arc::clone(&metrics));
    let mut first = budget.start_response();
    let mut second = budget.start_response();
    first.reserve_chunk(5).unwrap();
    second.reserve_chunk(3).unwrap();
    assert!(matches!(
        second.reserve_chunk(1),
        Err(ResponseBodyError::BudgetExceeded { limit: 8 })
    ));
    assert_eq!(metrics.snapshot().buffered_response_bytes, 8);
    assert_eq!(metrics.snapshot().buffered_response_budget_rejections, 1);
    drop(second);
    assert_eq!(metrics.snapshot().buffered_response_bytes, 5);
    drop(first);
    assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
    let mut next = budget.start_response();
    next.reserve_chunk(8).unwrap();
    drop(next);
    assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
}

#[test]
fn zero_budget_accepts_empty_chunk_only() {
    let metrics = Arc::new(Metrics::default());
    let budget = BufferedBodyBudget::new(Some(0), Arc::clone(&metrics));
    let mut reservation = budget.start_response();
    reservation.reserve_chunk(0).unwrap();
    reservation.release_chunk(0).unwrap();
    assert!(matches!(
        reservation.reserve_chunk(1),
        Err(ResponseBodyError::BudgetExceeded { limit: 0 })
    ));
    drop(reservation);
    assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
    assert_eq!(metrics.snapshot().buffered_response_budget_rejections, 1);
}

#[test]
fn reservation_and_aggregate_overflows_leave_accounting_unchanged() {
    let metrics = Arc::new(Metrics::default());
    let budget = BufferedBodyBudget::new(None, Arc::clone(&metrics));
    let mut first = budget.start_response();
    let mut second = budget.start_response();
    first.reserve_chunk(usize::MAX).unwrap();
    assert!(matches!(
        first.reserve_chunk(1),
        Err(ResponseBodyError::ReservationOverflow)
    ));
    assert!(matches!(
        second.reserve_chunk(1),
        Err(ResponseBodyError::CounterOverflow)
    ));
    assert_eq!(metrics.snapshot().buffered_response_bytes, usize::MAX);
    assert_eq!(metrics.snapshot().buffered_response_budget_rejections, 0);
    drop(second);
    assert_eq!(metrics.snapshot().buffered_response_bytes, usize::MAX);
    drop(first);
    assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
}
