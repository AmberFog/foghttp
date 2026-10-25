use super::{is_active, reject, send_fragments, UploadStartupGuard};
use crate::core::client::{
    upload_body_channel, upload_body_channel_with_budget, UploadBodyAccount, UploadBodyBudget,
};
use crate::errors::FogHttpLifecycleError;
use pyo3::exceptions::PyValueError;
use pyo3::{PyErr, Python};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;

fn assert_lifecycle_error(error: &PyErr) {
    Python::attach(|py| assert!(error.is_instance_of::<FogHttpLifecycleError>(py)));
}

#[test]
fn nested_upload_startups_match_outer_alias_and_leave_other_channel_usable() {
    Python::initialize();
    let (outer, _outer_receiver) = upload_body_channel(8);
    let outer_alias = outer.clone();
    let (inner, _inner_receiver) = upload_body_channel(8);
    let outer_scope = UploadStartupGuard::enter(&outer);
    let inner_scope = UploadStartupGuard::enter(&inner);
    assert!(is_active(&outer_alias));
    assert!(is_active(&inner));

    assert_lifecycle_error(&reject(&outer_alias));
    assert!(outer.is_closed());
    assert!(!inner.is_closed());
    inner_scope.complete(Ok(())).unwrap();
    assert!(!is_active(&inner));
    assert!(is_active(&outer));
    assert_lifecycle_error(&outer_scope.complete(Ok(())).unwrap_err());
    assert!(!is_active(&outer));
    assert!(inner.send_slice_blocking(b"usable", false));
}

#[test]
fn nested_upload_startups_mark_every_matching_channel_frame_rejected() {
    Python::initialize();
    let (sender, _receiver) = upload_body_channel(8);
    let outer = UploadStartupGuard::enter(&sender);
    let inner = UploadStartupGuard::enter(&sender.clone());
    assert_lifecycle_error(&reject(&sender));
    assert_lifecycle_error(&inner.complete(Ok(())).unwrap_err());
    assert_lifecycle_error(&outer.complete(Ok(())).unwrap_err());
    assert!(!is_active(&sender));
}

#[test]
fn upload_startup_unwind_cleans_thread_local_membership() {
    let (sender, _receiver) = upload_body_channel(8);
    let unwind = catch_unwind(AssertUnwindSafe(|| {
        let _scope = UploadStartupGuard::enter(&sender);
        assert!(is_active(&sender));
        panic!("startup callback unwound");
    }));
    assert!(unwind.is_err());
    assert!(!is_active(&sender));
    assert!(sender.send_slice_blocking(b"usable", false));
}

#[test]
fn upload_startup_membership_does_not_cross_producer_threads() {
    let (sender, _receiver) = upload_body_channel(8);
    let scope = UploadStartupGuard::enter(&sender);
    let worker_sender = sender.clone();
    assert!(!thread::spawn(move || is_active(&worker_sender))
        .join()
        .unwrap());
    assert!(is_active(&sender));
    scope.complete(Ok(())).unwrap();
    assert!(!is_active(&sender));
}

#[test]
fn upload_startup_keeps_callback_exception_primary_after_caught_rejection() {
    Python::initialize();
    let (sender, _receiver) = upload_body_channel(8);
    let scope = UploadStartupGuard::enter(&sender);
    assert_lifecycle_error(&reject(&sender));
    let primary = PyValueError::new_err("provider failed after catching admission error");
    let error = scope.complete(Err(primary)).unwrap_err();
    Python::attach(|py| assert!(error.is_instance_of::<PyValueError>(py)));
    assert_eq!(
        error.to_string(),
        "ValueError: provider failed after catching admission error"
    );
    assert!(!is_active(&sender));
}

#[test]
fn upload_startup_rejection_calls_channel_close_outside_thread_local_borrow() {
    Python::initialize();
    let (sender, _receiver) = upload_body_channel(8);
    let scope = UploadStartupGuard::enter(&sender);
    let callback_reentered = Arc::new(AtomicBool::new(false));
    let observed_reentry = Arc::clone(&callback_reentered);
    let callback_sender = sender.clone();
    sender.set_ready_callback(Some(Arc::new(move || {
        assert!(is_active(&callback_sender));
        observed_reentry.store(true, Ordering::Release);
    })));
    assert_lifecycle_error(&reject(&sender));
    assert!(callback_reentered.load(Ordering::Acquire));
    sender.set_ready_callback(None);
    assert_lifecycle_error(&scope.complete(Ok(())).unwrap_err());
}

#[test]
fn upload_startup_byte_rejection_discards_accepted_prefix_before_consumer_handoff() {
    Python::initialize();
    let budget = Arc::new(UploadBodyBudget::new(1));
    let account = Arc::new(UploadBodyAccount::new(1, Arc::clone(&budget)));
    let (sender, _receiver) = upload_body_channel_with_budget(8, Arc::clone(&account));
    let scope = UploadStartupGuard::enter(&sender);
    assert_lifecycle_error(&send_fragments(&sender, b"data", true).unwrap_err());
    assert!(sender.is_closed());
    assert_eq!(account.buffered_bytes(), 0);
    assert_eq!(budget.buffered_bytes(), 0);
    assert_lifecycle_error(&scope.complete(Ok(())).unwrap_err());
}
