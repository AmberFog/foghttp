use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::time::Duration;

pub(super) fn duration_as_nanos(duration: Duration) -> u64 {
    duration.as_nanos().try_into().unwrap_or(u64::MAX)
}

pub(super) fn saturating_atomic_u64_add(target: &AtomicU64, value: u64) {
    let mut current = target.load(Ordering::Relaxed);
    loop {
        let next = current.saturating_add(value);
        match target.compare_exchange_weak(current, next, Ordering::Relaxed, Ordering::Relaxed) {
            Ok(_previous) => return,
            Err(actual) => current = actual,
        }
    }
}

pub(super) fn update_atomic_usize_max(target: &AtomicUsize, value: usize) {
    let mut current = target.load(Ordering::Relaxed);
    while value > current {
        match target.compare_exchange_weak(current, value, Ordering::Relaxed, Ordering::Relaxed) {
            Ok(_previous) => return,
            Err(actual) => current = actual,
        }
    }
}

pub(super) fn update_atomic_u64_max(target: &AtomicU64, value: u64) {
    let mut current = target.load(Ordering::Relaxed);
    while value > current {
        match target.compare_exchange_weak(current, value, Ordering::Relaxed, Ordering::Relaxed) {
            Ok(_previous) => return,
            Err(actual) => current = actual,
        }
    }
}
