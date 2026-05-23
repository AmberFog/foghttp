use super::{ActiveStreamRead, StreamState, StreamStateFields, StreamStateInner};
use crate::core::metrics::{Metrics, ResponseBodyLifecycleOutcome};
use crate::py::client::async_requests::RequestCompletion;
use crate::py::client::streams::AsyncStreamRegistry;
use pyo3::prelude::*;
use pyo3::types::PyAny;
use std::sync::{Arc, Mutex, Once};
use std::time::Duration;
use tokio::runtime::{Builder, Runtime};

const TEST_ORIGIN: &str = "http://example.com";
const TEST_READ_TIMEOUT_SECS: f64 = 1.0;
const TEST_STREAM_ID: u64 = 1;

fn initialize_python() {
    static PYTHON: Once = Once::new();
    PYTHON.call_once(Python::initialize);
}

fn test_runtime() -> Runtime {
    Builder::new_current_thread().enable_time().build().unwrap()
}

fn finished_read_state() -> StreamState {
    StreamState {
        inner: Arc::new(StreamStateInner {
            stream_id: TEST_STREAM_ID,
            registry: AsyncStreamRegistry::default(),
            fields: Mutex::new(StreamStateFields {
                body: None,
                permit: None,
                lifecycle: None,
                connection_use: None,
                read_task: None,
                read_in_progress: true,
                finished: true,
                successful_body_outcome: ResponseBodyLifecycleOutcome::Closed,
                metrics: Arc::new(Metrics::default()),
                completion: RequestCompletion::default(),
                read_timeout: Duration::from_secs(1),
                read_timeout_secs: TEST_READ_TIMEOUT_SECS,
                origin: TEST_ORIGIN.to_string(),
                redirect_hop: 0,
            }),
        }),
    }
}

fn new_future(py: Python<'_>) -> PyResult<(Py<PyAny>, Py<PyAny>)> {
    let asyncio = py.import("asyncio")?;
    let event_loop = asyncio.call_method0("new_event_loop")?.unbind();
    let future = event_loop.bind(py).call_method0("create_future")?.unbind();
    Ok((event_loop, future))
}

fn run_scheduled_callbacks(py: Python<'_>, event_loop: &Py<PyAny>) -> PyResult<()> {
    let asyncio = py.import("asyncio")?;
    let sleep = asyncio.call_method1("sleep", (0,))?;
    event_loop
        .bind(py)
        .call_method1("run_until_complete", (sleep,))?;
    Ok(())
}

#[test]
fn rejected_read_task_cancels_python_future_instead_of_reporting_eof() {
    initialize_python();
    let state = finished_read_state();
    let runtime = test_runtime();
    let handle = runtime.spawn(async {
        std::future::pending::<()>().await;
    });

    Python::attach(|py| -> PyResult<()> {
        let (event_loop, future) = new_future(py)?;
        let accepted = state.register_read_task(ActiveStreamRead::new(
            handle.abort_handle(),
            event_loop.clone_ref(py),
            future.clone_ref(py),
        ));

        assert!(!accepted);
        run_scheduled_callbacks(py, &event_loop)?;
        assert!(future
            .bind(py)
            .call_method0("cancelled")?
            .extract::<bool>()?);
        event_loop.bind(py).call_method0("close")?;
        Ok(())
    })
    .unwrap();

    let join_error = runtime
        .block_on(handle)
        .expect_err("rejected stream read task should be aborted");
    assert!(join_error.is_cancelled());
}
