use super::{RawUploadBody, RawUploadBodyInner};
use crate::core::client::streaming_request_body;
use http_body_util::BodyExt;
use pyo3::ffi::c_str;
use pyo3::{PyResult, Python};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Once};
use tokio::runtime::Builder;

fn initialize_python() {
    static PYTHON: Once = Once::new();
    PYTHON.call_once(Python::initialize);
}

#[test]
fn zero_length_upload_waits_for_explicit_producer_completion() {
    initialize_python();
    Python::attach(|py| -> PyResult<()> {
        let callback = py.eval(c_str!("lambda body: None"), None, None)?.unbind();
        let body = RawUploadBody::new(Some(0), callback, false, None);
        let (receiver, content_length) = body.take_receiver(py)?;
        let (mut request_body, completion) = streaming_request_body(receiver, content_length, None);

        assert!(!completion.is_complete());
        body.finish();
        assert!(!completion.is_complete());
        let frame = Builder::new_current_thread()
            .build()
            .unwrap()
            .block_on(request_body.frame());

        assert!(frame.is_none());
        assert!(!completion.is_complete());
        completion.mark_transport_flushed();
        assert!(completion.is_complete());
        Ok(())
    })
    .unwrap();
}

#[test]
fn empty_final_chunk_reports_success_only_when_it_closes_the_channel() {
    initialize_python();
    Python::attach(|py| -> PyResult<()> {
        let callback = py.eval(c_str!("lambda body: None"), None, None)?.unbind();
        let blocking = RawUploadBody::new(None, callback.clone_ref(py), false, None);
        let nonblocking = RawUploadBody::new(None, callback, false, None);

        assert!(blocking.send_final(py, b""));
        assert!(!blocking.send_final(py, b""));
        assert!(nonblocking.send_final_nowait(b""));
        assert!(!nonblocking.send_final_nowait(b""));
        Ok(())
    })
    .unwrap();
}

#[test]
fn replay_reset_invokes_ready_callback_without_holding_owner_lock() {
    initialize_python();
    Python::attach(|py| -> PyResult<()> {
        let start_callback = py.eval(c_str!("lambda body: None"), None, None)?.unbind();
        let body = RawUploadBody::new(None, start_callback, true, None);
        let RawUploadBodyInner::Owner(state) = &body.inner else {
            unreachable!("new upload body owns its channel state");
        };
        let lock_was_available = Arc::new(AtomicBool::new(false));
        let ready_callback: Arc<dyn Fn() + Send + Sync> = {
            let state = Arc::clone(state);
            let lock_was_available = Arc::clone(&lock_was_available);
            Arc::new(move || {
                lock_was_available.store(state.try_lock().is_ok(), Ordering::Release);
            })
        };
        {
            let mut state = state.lock().expect("raw upload body lock poisoned");
            state.ready_callback = Some(Arc::clone(&ready_callback));
            state
                .sender
                .as_ref()
                .expect("new upload body owns its sender")
                .set_ready_callback(Some(ready_callback));
        }

        let (_first_receiver, _) = body.take_receiver(py)?;
        let (_second_receiver, _) = body.take_receiver(py)?;

        assert!(lock_was_available.load(Ordering::Acquire));
        Ok(())
    })
    .unwrap();
}
