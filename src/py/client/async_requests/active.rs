use crate::core::metrics::Metrics;
use crate::py::client::future::cancel_python_future;
use pyo3::prelude::*;
use pyo3::types::PyAny;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use tokio::task::AbortHandle;

pub(super) struct ActiveAsyncRequest {
    abort_handle: AbortHandle,
    loop_: Py<PyAny>,
    future: Py<PyAny>,
    metrics: Arc<Metrics>,
    completion: RequestCompletion,
}

impl ActiveAsyncRequest {
    pub(super) fn new(
        abort_handle: AbortHandle,
        loop_: Py<PyAny>,
        future: Py<PyAny>,
        metrics: Arc<Metrics>,
        completion: RequestCompletion,
    ) -> Self {
        Self {
            abort_handle,
            loop_,
            future,
            metrics,
            completion,
        }
    }

    pub(super) fn abort(self) {
        let Self {
            abort_handle,
            metrics,
            completion,
            ..
        } = self;

        if completion.finish() {
            abort_handle.abort();
            metrics.request_finished(true);
        }
    }

    pub(super) fn abort_and_cancel_python(self) {
        let Self {
            abort_handle,
            loop_,
            future,
            metrics,
            completion,
        } = self;

        if completion.finish() {
            abort_handle.abort();
            metrics.request_finished(true);
        }
        cancel_python_future(&loop_, &future);
    }
}

#[derive(Clone, Default)]
pub(crate) struct RequestCompletion {
    finished: Arc<AtomicBool>,
}

impl RequestCompletion {
    pub(crate) fn finish(&self) -> bool {
        self.finished
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .is_ok()
    }

    pub(super) fn is_finished(&self) -> bool {
        self.finished.load(Ordering::Acquire)
    }
}
