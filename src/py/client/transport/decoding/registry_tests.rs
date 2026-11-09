use super::super::test_control::{DecodeCheckpointTarget, DecodeTestControl};
use super::test_fixtures::{encoded_case, reach_checkpoint, ControlledDecode, BODY_SIZE, WATCHDOG};
use crate::core::metrics::Metrics;
use crate::core::response::{response_body_decoding_plan, BufferedBodyBudget, CollectedBody};
use crate::py::client::acquire::AcquireGate;
use crate::py::client::async_requests::{test_support, AsyncRequestRegistry};
use crate::py::client::transport::context::RawResponseContext;
use hyper::header::CONTENT_ENCODING;
use hyper::HeaderMap;
use pyo3::prelude::*;
use std::sync::Arc;
use std::time::Instant;
use tokio::runtime::Builder;

enum Cancellation {
    PythonFuture,
    ClientClose,
}

struct PythonLoop {
    loop_: Py<PyAny>,
    future: Py<PyAny>,
}

impl PythonLoop {
    fn new() -> Self {
        Python::attach(|py| {
            let loop_ = py
                .import("asyncio")
                .unwrap()
                .call_method0("new_event_loop")
                .unwrap();
            let future = loop_.call_method0("create_future").unwrap().unbind();
            Self {
                loop_: loop_.unbind(),
                future,
            }
        })
    }

    fn drain(&self) {
        Python::attach(|py| {
            let turn = py
                .import("asyncio")
                .unwrap()
                .call_method1("sleep", (0,))
                .unwrap();
            self.loop_
                .bind(py)
                .call_method1("run_until_complete", (turn,))
                .unwrap();
        });
    }
}

impl Drop for PythonLoop {
    fn drop(&mut self) {
        Python::attach(|py| {
            self.loop_.bind(py).call_method0("close").unwrap();
        });
    }
}

async fn admitted_decode(target: DecodeCheckpointTarget) -> (ControlledDecode, AcquireGate) {
    let metrics = Arc::new(Metrics::default());
    let acquire = AcquireGate::new(1, None, 1, Arc::clone(&metrics));
    let permit = acquire
        .acquire("http://collected.example", 10.0, 0)
        .await
        .unwrap();
    let (encoded_body, coding) = encoded_case(target);
    let budget = BufferedBodyBudget::new(Some(BODY_SIZE * 4), Arc::clone(&metrics));
    let mut reservation = budget.start_response();
    reservation.reserve_chunk(encoded_body.len()).unwrap();
    let collected = CollectedBody {
        content: encoded_body,
        reservation,
    };
    let mut headers = HeaderMap::new();
    headers.insert(CONTENT_ENCODING, coding.parse().unwrap());
    let plan = response_body_decoding_plan(&headers);
    let (control, reached, release) = DecodeTestControl::new(target);
    let control = Arc::new(control);
    let task_control = Arc::clone(&control);
    let started = Instant::now();
    let task = tokio::spawn(async move {
        let _permit = permit;
        let decode_context = RawResponseContext {
            started,
            total_timeout: 30.0,
            read_timeout: 10.0,
            max_response_body_size: Some(BODY_SIZE),
            buffered_body_budget: budget,
            buffered_decoders: Arc::new(tokio::sync::Semaphore::new(1)),
            origin: "http://collected.example",
            redirect_hop: 0,
            decode_checkpoint: Some(&task_control),
        };
        super::super::decode_response_body(collected, plan, &decode_context).await
    });
    (
        ControlledDecode {
            control,
            reached,
            release,
            task,
            metrics,
            started,
        },
        acquire,
    )
}

#[test]
fn python_cancellation_and_client_close_abort_admitted_post_eof_decode() {
    Python::initialize();
    let runtime = Builder::new_current_thread().enable_time().build().unwrap();
    for cancellation in [Cancellation::PythonFuture, Cancellation::ClientClose] {
        for target in [
            DecodeCheckpointTarget::Output {
                layer: 0,
                minimum: 1,
            },
            DecodeCheckpointTarget::BetweenLayers { remaining: 1 },
            DecodeCheckpointTarget::RawDeflate,
            DecodeCheckpointTarget::Finished,
        ] {
            runtime.block_on(async {
                let (
                    ControlledDecode {
                        control,
                        reached,
                        release,
                        task,
                        metrics,
                        ..
                    },
                    acquire,
                ) = admitted_decode(target).await;
                let registry = AsyncRequestRegistry::default();
                let python_loop = PythonLoop::new();
                metrics.request_started();
                let completion = Python::attach(|py| {
                    test_support::register_request(
                        py,
                        &registry,
                        task.abort_handle(),
                        &python_loop.loop_,
                        &python_loop.future,
                        Arc::clone(&metrics),
                    )
                    .unwrap()
                });
                reach_checkpoint(reached).await;
                let paused = metrics.snapshot();
                assert_eq!(paused.total_requests, 1);
                assert_eq!(paused.active_requests, 1);
                assert_eq!(paused.pending_requests, 0);
                assert!(paused.buffered_response_bytes > 0);
                let visits = control.visits();
                match cancellation {
                    Cancellation::PythonFuture => {
                        Python::attach(|py| {
                            python_loop.future.bind(py).call_method0("cancel").unwrap();
                        });
                    }
                    Cancellation::ClientClose => registry.abort_all(),
                }
                python_loop.drain();
                let result = tokio::time::timeout(WATCHDOG, task).await.unwrap();
                assert!(result.is_err_and(|error| error.is_cancelled()));
                assert!(
                    !completion.finish(),
                    "request completion was already claimed by cancellation"
                );
                release
                    .send(())
                    .expect_err("aborted future must drop its checkpoint receiver");
                Python::attach(|py| {
                    assert!(python_loop
                        .future
                        .bind(py)
                        .call_method0("cancelled")
                        .unwrap()
                        .extract::<bool>()
                        .unwrap());
                });
                registry.abort_all();
                python_loop.drain();
                tokio::task::yield_now().await;
                let stopped = metrics.snapshot();
                assert_eq!(stopped.total_requests, 1);
                assert_eq!(stopped.failed_requests, 1);
                assert_eq!(stopped.active_requests, 0);
                assert_eq!(stopped.pending_requests, 0);
                assert_eq!(stopped.buffered_response_bytes, 0);
                assert_eq!(
                    control.visits(),
                    visits,
                    "decode continued after task quiescence"
                );
                let recovery = tokio::time::timeout(
                    WATCHDOG,
                    acquire.acquire("http://collected.example", 10.0, 0),
                )
                .await
                .unwrap()
                .unwrap();
                assert_eq!(metrics.snapshot().active_requests, 1);
                drop(recovery);
                assert_eq!(metrics.snapshot().active_requests, 0);
            });
        }
    }
}
