use crate::core::client::{UploadBodySendError, UploadBodySender};
use crate::errors::FogHttpLifecycleError;
use pyo3::{PyErr, PyResult};
use std::cell::{Cell, RefCell};
use std::rc::Rc;

const STARTUP_SEND_WOULD_WAIT: &str = "blocking upload send from start_callback would wait before its consumer can start; start a producer worker or use nonblocking sends";

thread_local! {
    static ACTIVE_CALLBACKS: RefCell<Vec<Rc<UploadStartupFrame>>> = const { RefCell::new(Vec::new()) };
}

struct UploadStartupFrame {
    sender: UploadBodySender,
    rejected: Cell<bool>,
}

pub(super) struct UploadStartupGuard {
    frame: Rc<UploadStartupFrame>,
}

impl UploadStartupGuard {
    pub(super) fn enter(sender: &UploadBodySender) -> Self {
        let frame = Rc::new(UploadStartupFrame {
            sender: sender.clone(),
            rejected: Cell::new(false),
        });
        ACTIVE_CALLBACKS.with(|callbacks| callbacks.borrow_mut().push(Rc::clone(&frame)));
        Self { frame }
    }

    pub(super) fn complete(self, callback_result: PyResult<()>) -> PyResult<()> {
        let rejected = self.frame.rejected.get();
        drop(self);
        callback_result?;
        if rejected {
            return Err(FogHttpLifecycleError::new_err(STARTUP_SEND_WOULD_WAIT));
        }
        Ok(())
    }
}

impl Drop for UploadStartupGuard {
    fn drop(&mut self) {
        let popped = ACTIVE_CALLBACKS.with(|callbacks| callbacks.borrow_mut().pop());
        debug_assert!(popped
            .as_ref()
            .is_some_and(|frame| Rc::ptr_eq(frame, &self.frame)));
        drop(popped);
    }
}

pub(super) fn is_active(sender: &UploadBodySender) -> bool {
    ACTIVE_CALLBACKS.with(|callbacks| {
        callbacks
            .borrow()
            .iter()
            .any(|frame| frame.sender.is_same_channel(sender))
    })
}

pub(super) fn reject(sender: &UploadBodySender) -> PyErr {
    ACTIVE_CALLBACKS.with(|callbacks| {
        for frame in callbacks.borrow().iter() {
            if frame.sender.is_same_channel(sender) {
                frame.rejected.set(true);
            }
        }
    });
    sender.close();
    FogHttpLifecycleError::new_err(STARTUP_SEND_WOULD_WAIT)
}

pub(super) fn send_fragments(
    sender: &UploadBodySender,
    chunk: &[u8],
    final_chunk: bool,
) -> PyResult<bool> {
    let fragments = chunk.chunks(sender.max_chunk_size());
    let last_index = fragments.len() - 1;
    for (index, fragment) in fragments.enumerate() {
        match sender.send_slice_nowait(fragment, final_chunk && index == last_index) {
            Ok(()) => {}
            Err(UploadBodySendError::Closed) => return Ok(false),
            Err(UploadBodySendError::Full) => return Err(reject(sender)),
        }
    }
    Ok(true)
}

#[cfg(test)]
mod tests;
