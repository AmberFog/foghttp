use crate::core::client::{
    upload_body_channel, UploadBodyReceiver, UploadBodySendError, UploadBodySender,
};
use bytes::Bytes;
use pyo3::prelude::*;
use pyo3::types::PyAny;
use std::sync::{Arc, Mutex};

const UPLOAD_BODY_CHANNEL_CAPACITY: usize = 8;
const STREAMING_BODY_CONSUMED: &str = "streaming request body was already consumed";

#[pyclass(module = "foghttp._foghttp", skip_from_py_object)]
#[derive(Clone)]
pub struct RawUploadBody {
    inner: RawUploadBodyInner,
}

#[derive(Clone)]
enum RawUploadBodyInner {
    Owner(Arc<Mutex<RawUploadBodyState>>),
    Attempt(UploadBodySender),
}

struct RawUploadBodyState {
    sender: Option<UploadBodySender>,
    receiver: Option<UploadBodyReceiver>,
    content_length: Option<u64>,
    start_callback: Arc<Py<PyAny>>,
    replayable: bool,
    ready_callback: Option<Arc<dyn Fn() + Send + Sync>>,
}

#[pymethods]
impl RawUploadBody {
    #[new]
    fn new(
        content_length: Option<u64>,
        start_callback: Py<PyAny>,
        replayable: bool,
        ready_callback: Option<Py<PyAny>>,
    ) -> Self {
        let ready_callback = ready_callback.map(ready_callback_wrapper);
        let (sender, receiver) = new_upload_body_channel(ready_callback.as_ref());
        Self {
            inner: RawUploadBodyInner::Owner(Arc::new(Mutex::new(RawUploadBodyState {
                sender: Some(sender),
                receiver: Some(receiver),
                content_length,
                start_callback: Arc::new(start_callback),
                replayable,
                ready_callback,
            }))),
        }
    }

    fn send(&self, py: Python<'_>, chunk: &[u8]) -> bool {
        if chunk.is_empty() {
            return self.sender().is_some_and(|sender| !sender.is_closed());
        }
        let Some(sender) = self.sender() else {
            return false;
        };
        let item = Ok(Bytes::copy_from_slice(chunk));
        py.detach(|| sender.send_blocking(item))
    }

    fn send_final(&self, py: Python<'_>, chunk: &[u8]) -> bool {
        if chunk.is_empty() {
            return self.take_sender().is_some_and(|sender| sender.finish());
        }
        let Some(sender) = self.sender() else {
            return false;
        };
        let item = Ok(Bytes::copy_from_slice(chunk));
        py.detach(|| sender.send_final_blocking(item))
    }

    fn send_nowait(&self, chunk: &[u8]) -> bool {
        if chunk.is_empty() {
            return self.sender().is_some_and(|sender| !sender.is_closed());
        }
        let Some(sender) = self.sender() else {
            return false;
        };
        matches!(
            sender.send_nowait(Ok(Bytes::copy_from_slice(chunk))),
            Ok(())
        )
    }

    fn send_final_nowait(&self, chunk: &[u8]) -> bool {
        if chunk.is_empty() {
            return self.take_sender().is_some_and(|sender| sender.finish());
        }
        let Some(sender) = self.sender() else {
            return false;
        };
        matches!(
            sender.send_final_nowait(Ok(Bytes::copy_from_slice(chunk))),
            Ok(())
        )
    }

    fn is_closed(&self) -> bool {
        match self.sender() {
            Some(sender) => sender.is_closed(),
            None => true,
        }
    }

    fn finish(&self) {
        if let Some(sender) = self.take_sender() {
            sender.finish();
        }
    }

    fn fail(&self, py: Python<'_>, message: String) {
        let Some(sender) = self.take_sender() else {
            return;
        };
        let _sent = py.detach(|| sender.send_blocking(Err(message)));
        sender.finish();
    }

    fn fail_nowait(&self, message: String) -> bool {
        let Some(sender) = self.sender() else {
            return true;
        };
        match sender.send_nowait(Err(message)) {
            Ok(()) => {
                self.take_sender();
                sender.finish();
                true
            }
            Err(UploadBodySendError::Full) => false,
            Err(UploadBodySendError::Closed) => true,
        }
    }

    fn close(&self) {
        if let Some(sender) = self.take_sender() {
            sender.close();
        }
    }
}

impl RawUploadBody {
    pub(crate) fn take_receiver(
        &self,
        py: Python<'_>,
    ) -> PyResult<(UploadBodyReceiver, Option<u64>)> {
        let RawUploadBodyInner::Owner(state) = &self.inner else {
            return Err(pyo3::exceptions::PyRuntimeError::new_err(
                STREAMING_BODY_CONSUMED,
            ));
        };
        let (receiver, content_length, start_callback, attempt_sender, previous_sender) = {
            let mut state = state.lock().expect("raw upload body lock poisoned");
            let previous_sender = if state.receiver.is_none() {
                if !state.replayable {
                    return Err(pyo3::exceptions::PyRuntimeError::new_err(
                        STREAMING_BODY_CONSUMED,
                    ));
                }
                state.reset_channel()
            } else {
                None
            };
            let Some(receiver) = state.receiver.take() else {
                return Err(pyo3::exceptions::PyRuntimeError::new_err(
                    STREAMING_BODY_CONSUMED,
                ));
            };
            let Some(attempt_sender) = state.sender.clone() else {
                return Err(pyo3::exceptions::PyRuntimeError::new_err(
                    STREAMING_BODY_CONSUMED,
                ));
            };
            (
                receiver,
                state.content_length,
                Arc::clone(&state.start_callback),
                attempt_sender,
                previous_sender,
            )
        };
        if let Some(sender) = previous_sender {
            sender.close();
        }

        let attempt_body = Py::new(
            py,
            Self {
                inner: RawUploadBodyInner::Attempt(attempt_sender.clone()),
            },
        )?;
        if let Err(error) = start_callback.bind(py).call1((attempt_body,)) {
            attempt_sender.close();
            return Err(error);
        }
        Ok((receiver, content_length))
    }

    fn sender(&self) -> Option<UploadBodySender> {
        match &self.inner {
            RawUploadBodyInner::Owner(state) => state
                .lock()
                .expect("raw upload body lock poisoned")
                .sender
                .clone(),
            RawUploadBodyInner::Attempt(sender) => Some(sender.clone()),
        }
    }

    fn take_sender(&self) -> Option<UploadBodySender> {
        match &self.inner {
            RawUploadBodyInner::Owner(state) => state
                .lock()
                .expect("raw upload body lock poisoned")
                .sender
                .take(),
            RawUploadBodyInner::Attempt(sender) => Some(sender.clone()),
        }
    }
}

impl RawUploadBodyState {
    fn reset_channel(&mut self) -> Option<UploadBodySender> {
        let previous_sender = self.sender.take();
        let (sender, receiver) = new_upload_body_channel(self.ready_callback.as_ref());
        self.sender = Some(sender);
        self.receiver = Some(receiver);
        previous_sender
    }
}

fn new_upload_body_channel(
    ready_callback: Option<&Arc<dyn Fn() + Send + Sync>>,
) -> (UploadBodySender, UploadBodyReceiver) {
    let (sender, receiver) = upload_body_channel(UPLOAD_BODY_CHANNEL_CAPACITY);
    if let Some(callback) = ready_callback {
        sender.set_ready_callback(Some(Arc::clone(callback)));
    }
    (sender, receiver)
}

fn ready_callback_wrapper(callback: Py<PyAny>) -> Arc<dyn Fn() + Send + Sync> {
    Arc::new(move || {
        Python::attach(|py| {
            if let Err(error) = callback.bind(py).call0() {
                error.write_unraisable(py, Some(callback.bind(py)));
            }
        });
    })
}

#[cfg(test)]
mod tests {
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
            let (mut request_body, completion) =
                streaming_request_body(receiver, content_length, None);

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
}
