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
    start_callback: Py<PyAny>,
    replayable: bool,
    ready_callback: Option<Py<PyAny>>,
}

#[pymethods]
impl RawUploadBody {
    #[new]
    fn new(
        py: Python<'_>,
        content_length: Option<u64>,
        start_callback: Py<PyAny>,
        replayable: bool,
        ready_callback: Option<Py<PyAny>>,
    ) -> Self {
        let (sender, receiver) = new_upload_body_channel(py, ready_callback.as_ref());
        Self {
            inner: RawUploadBodyInner::Owner(Arc::new(Mutex::new(RawUploadBodyState {
                sender: Some(sender),
                receiver: Some(receiver),
                content_length,
                start_callback,
                replayable,
                ready_callback,
            }))),
        }
    }

    fn send(&self, py: Python<'_>, chunk: &[u8]) -> bool {
        if chunk.is_empty() {
            return true;
        }
        let Some(sender) = self.sender() else {
            return false;
        };
        let item = Ok(Bytes::copy_from_slice(chunk));
        py.detach(|| sender.send_blocking(item))
    }

    fn send_nowait(&self, chunk: &[u8]) -> bool {
        if chunk.is_empty() {
            return true;
        }
        let Some(sender) = self.sender() else {
            return false;
        };
        matches!(
            sender.send_nowait(Ok(Bytes::copy_from_slice(chunk))),
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
        let (receiver, content_length, start_callback, attempt_sender) = {
            let mut state = state.lock().expect("raw upload body lock poisoned");
            if state.receiver.is_none() {
                if !state.replayable {
                    return Err(pyo3::exceptions::PyRuntimeError::new_err(
                        STREAMING_BODY_CONSUMED,
                    ));
                }
                state.reset_channel(py);
            }
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
                state.start_callback.clone_ref(py),
                attempt_sender,
            )
        };

        let attempt_body = Py::new(
            py,
            Self {
                inner: RawUploadBodyInner::Attempt(attempt_sender.clone()),
            },
        )?;
        if let Err(error) = start_callback.call1(py, (attempt_body,)) {
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
    fn reset_channel(&mut self, py: Python<'_>) {
        if let Some(sender) = self.sender.take() {
            sender.close();
        }
        let (sender, receiver) = new_upload_body_channel(py, self.ready_callback.as_ref());
        self.sender = Some(sender);
        self.receiver = Some(receiver);
    }
}

fn new_upload_body_channel(
    py: Python<'_>,
    ready_callback: Option<&Py<PyAny>>,
) -> (UploadBodySender, UploadBodyReceiver) {
    let (sender, receiver) = upload_body_channel(UPLOAD_BODY_CHANNEL_CAPACITY);
    if let Some(callback) = ready_callback {
        sender.set_ready_callback(Some(ready_callback_wrapper(callback.clone_ref(py))));
    }
    (sender, receiver)
}

fn ready_callback_wrapper(callback: Py<PyAny>) -> Arc<dyn Fn() + Send + Sync> {
    let callback = Arc::new(Mutex::new(callback));
    Arc::new(move || {
        Python::attach(|py| {
            let callback = callback.lock().expect("upload body callback lock poisoned");
            if let Err(error) = callback.bind(py).call0() {
                error.write_unraisable(py, Some(callback.bind(py)));
            }
        });
    })
}
