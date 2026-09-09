use super::{
    drain_ready_data_frames_with, ActiveStreamRead, ReadyBodyFrame, ReadyFrameDrain, StreamState,
    StreamStateFields, StreamStateInner,
};
use crate::core::metrics::{Metrics, ResponseBodyLifecycleOutcome};
use crate::py::client::async_requests::RequestCompletion;
use crate::py::client::lifecycle::ResponseBodyLifecycle;
use crate::py::client::streams::constants::{
    MAX_READY_FRAME_COALESCE_COUNT, READY_FRAME_COALESCE_TARGET_BYTES,
};
use crate::py::client::streams::StreamRegistry;
use bytes::Bytes;
use pyo3::prelude::*;
use pyo3::types::PyAny;
use std::collections::VecDeque;
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
            registry: StreamRegistry::default(),
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
                deferred_body_error: None,
            }),
        }),
    }
}

fn active_lifecycle_state() -> (StreamState, Arc<Metrics>, RequestCompletion) {
    let metrics = Arc::new(Metrics::default());
    let completion = RequestCompletion::default();
    let registry = StreamRegistry::default();
    let inner = Arc::new(StreamStateInner {
        stream_id: TEST_STREAM_ID,
        registry: registry.clone(),
        fields: Mutex::new(StreamStateFields {
            body: None,
            permit: None,
            lifecycle: Some(ResponseBodyLifecycle::new(
                Arc::clone(&metrics),
                metrics.origin_metrics(TEST_ORIGIN),
            )),
            connection_use: None,
            read_task: None,
            read_in_progress: false,
            finished: false,
            successful_body_outcome: ResponseBodyLifecycleOutcome::Closed,
            metrics: Arc::clone(&metrics),
            completion: completion.clone(),
            read_timeout: Duration::from_secs(1),
            read_timeout_secs: TEST_READ_TIMEOUT_SECS,
            origin: TEST_ORIGIN.to_string(),
            redirect_hop: 0,
            deferred_body_error: None,
        }),
    });
    registry.insert(TEST_STREAM_ID, &inner);
    (StreamState { inner }, metrics, completion)
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
        let accepted = state.register_read_task(ActiveStreamRead::new_async(
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

#[test]
fn cancel_is_idempotent_and_wins_over_later_close() {
    let (state, metrics, completion) = active_lifecycle_state();

    state.cancel();
    state.close();
    state.cancel();

    assert!(state.is_finished());
    assert!(!completion.finish());
    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.failed_requests, 1);
    assert_eq!(snapshot.response_body_aborted, 1);
    assert_eq!(snapshot.response_body_closed, 0);
}

#[test]
fn cancel_after_success_does_not_reclassify_stream() {
    let (state, metrics, completion) = active_lifecycle_state();

    state.finish_success_from_read();
    state.cancel();

    assert!(state.is_finished());
    assert!(!completion.finish());
    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.failed_requests, 0);
    assert_eq!(snapshot.response_body_aborted, 0);
    assert_eq!(snapshot.response_body_closed, 1);
}

#[test]
fn ready_frame_coalescing_merges_ready_data_until_eof() {
    let mut chunk = Bytes::from_static(b"first");
    let mut frames = VecDeque::from([
        ReadyBodyFrame::Data(Bytes::from_static(b"second")),
        ReadyBodyFrame::Data(Bytes::from_static(b"third")),
        ReadyBodyFrame::Eof,
    ]);

    let outcome = drain_ready_data_frames_with(&mut chunk, || frames.pop_front().unwrap());

    assert!(matches!(outcome, ReadyFrameDrain::Eof));
    assert_eq!(chunk.as_ref(), b"firstsecondthird");
}

#[test]
fn ready_frame_coalescing_stops_on_pending_without_consuming_later_frames() {
    let mut chunk = Bytes::from_static(b"first");
    let mut frames = VecDeque::from([
        ReadyBodyFrame::Data(Bytes::from_static(b"second")),
        ReadyBodyFrame::Pending,
        ReadyBodyFrame::Data(Bytes::from_static(b"third")),
    ]);

    let outcome = drain_ready_data_frames_with(&mut chunk, || frames.pop_front().unwrap());

    assert!(matches!(outcome, ReadyFrameDrain::Stopped));
    assert_eq!(chunk.as_ref(), b"firstsecond");
    assert!(matches!(frames.pop_front(), Some(ReadyBodyFrame::Data(_))));
}

#[test]
fn ready_frame_coalescing_returns_collected_data_before_deferred_error() {
    let mut chunk = Bytes::from_static(b"first");
    let mut frames = VecDeque::from([
        ReadyBodyFrame::Data(Bytes::from_static(b"second")),
        ReadyBodyFrame::Error("broken body".to_string()),
    ]);

    let outcome = drain_ready_data_frames_with(&mut chunk, || frames.pop_front().unwrap());

    assert!(matches!(outcome, ReadyFrameDrain::Error(error) if error == "broken body"));
    assert_eq!(chunk.as_ref(), b"firstsecond");
}

#[test]
fn ready_frame_coalescing_respects_count_and_byte_targets() {
    let mut chunk = Bytes::new();
    let mut poll_count = 0;
    let outcome = drain_ready_data_frames_with(&mut chunk, || {
        poll_count += 1;
        ReadyBodyFrame::Data(Bytes::from_static(b"x"))
    });

    assert!(matches!(outcome, ReadyFrameDrain::Stopped));
    assert_eq!(poll_count, MAX_READY_FRAME_COALESCE_COUNT - 1);
    assert_eq!(chunk.len(), MAX_READY_FRAME_COALESCE_COUNT - 1);

    let mut chunk = Bytes::from(vec![b'a'; READY_FRAME_COALESCE_TARGET_BYTES - 1]);
    let mut poll_count = 0;
    let outcome = drain_ready_data_frames_with(&mut chunk, || {
        poll_count += 1;
        ReadyBodyFrame::Data(Bytes::from_static(b"xy"))
    });

    assert!(matches!(outcome, ReadyFrameDrain::Stopped));
    assert_eq!(poll_count, 1);
    assert_eq!(chunk.len(), READY_FRAME_COALESCE_TARGET_BYTES + 1);
}

#[test]
#[ignore = "manual release-mode boundary measurement; no timing assertion"]
fn measure_streaming_boundary_conversion() {
    use pyo3::types::PyBytes;
    use std::hint::black_box;
    use std::time::Instant;

    initialize_python();
    Python::attach(|py| {
        for size in [4096, 65_536, 262_144] {
            for frames in [1, 2] {
                let data = Bytes::from(vec![b'x'; size / frames]);
                let iterations = u32::try_from(256 * 1024 * 1024 / size).unwrap();
                for warmup in [true, false] {
                    let start = Instant::now();
                    for _ in 0..iterations {
                        // Match the initial frame handoff in read_next_chunk.
                        let mut chunk = black_box(&data).clone();
                        let mut remaining = frames - 1;
                        let outcome = drain_ready_data_frames_with(&mut chunk, || {
                            if remaining == 0 {
                                ReadyBodyFrame::Pending
                            } else {
                                remaining -= 1;
                                ReadyBodyFrame::Data(data.clone())
                            }
                        });
                        black_box(outcome);
                        black_box(PyBytes::new(py, &chunk));
                    }
                    if !warmup {
                        println!(
                            "boundary size={size} frames={frames} iterations={iterations} ns_per_chunk={:.1}",
                            start.elapsed().as_secs_f64() * 1e9 / f64::from(iterations),
                        );
                    }
                }
            }
        }
    });
}

#[test]
fn single_ready_frame_keeps_owned_storage_until_python_conversion() {
    for frame in [
        ReadyBodyFrame::Pending,
        ReadyBodyFrame::Eof,
        ReadyBodyFrame::Error("broken body".to_string()),
    ] {
        let owner = Bytes::from(vec![b'x'; 4096]);
        let mut chunk = owner.slice(10..20);
        let original = chunk.as_ptr();
        let mut frame = Some(frame);
        let _ = drain_ready_data_frames_with(&mut chunk, || frame.take().unwrap());
        drop(owner);

        assert_eq!(chunk.as_ptr(), original);
        assert_eq!(chunk.as_ref(), &[b'x'; 10]);
    }
}

#[test]
fn ready_frame_at_byte_target_is_not_polled_or_copied() {
    for size in [
        READY_FRAME_COALESCE_TARGET_BYTES,
        READY_FRAME_COALESCE_TARGET_BYTES + 1,
    ] {
        let mut chunk = Bytes::from(vec![b'x'; size]);
        let original = chunk.as_ptr();
        let outcome = drain_ready_data_frames_with(&mut chunk, || panic!("must not poll"));

        assert!(matches!(outcome, ReadyFrameDrain::Stopped));
        assert_eq!(chunk.as_ptr(), original);
        assert_eq!(chunk.len(), size);
    }
}
