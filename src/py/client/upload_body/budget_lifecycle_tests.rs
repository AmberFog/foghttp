use super::{new_upload_body_channel, RawUploadBody, RawUploadBodyInner, RawUploadBodyState};
use crate::core::client::{
    request_write_timeout_from_error, streaming_request_body, RequestWriteTimeoutContext,
    UploadBodyAccount, UploadBodyBudget,
};
use crate::core::metrics::Metrics;
use crate::py::client::acquire::AcquireGate;
use crate::py::client::async_requests::{test_support, AsyncRequestRegistry};
use http_body_util::BodyExt;
use pyo3::ffi::c_str;
use pyo3::prelude::*;
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::Duration;
use tokio::runtime::Builder;

const ORIGIN: &str = "http://upload.example";
const WATCHDOG: Duration = Duration::from_secs(2);

fn upload(py: Python<'_>, budget: &Arc<UploadBodyBudget>) -> PyResult<RawUploadBody> {
    let account = Arc::new(UploadBodyAccount::new(4, Arc::clone(budget)));
    let (sender, receiver) = new_upload_body_channel(None, &account);
    let start_callback = py.eval(c_str!("lambda body: None"), None, None)?.unbind();
    Ok(RawUploadBody {
        account,
        inner: RawUploadBodyInner::Owner(Arc::new(Mutex::new(RawUploadBodyState {
            sender: Some(sender),
            receiver: Some(receiver),
            content_length: None,
            start_callback: Arc::new(start_callback),
            replayable: false,
            ready_callback: None,
        }))),
    })
}

fn start_blocked_send(raw: &RawUploadBody) -> (mpsc::Receiver<bool>, thread::JoinHandle<()>) {
    let raw = raw.clone();
    let (done, result) = mpsc::channel();
    let thread = thread::spawn(move || {
        let sent = Python::attach(|py| raw.send(py, b"next").unwrap());
        done.send(sent).unwrap();
    });
    (result, thread)
}

enum ProducerTermination {
    Finish,
    EmptyFinal,
    Fail,
    FailNowait,
}

#[test]
fn owner_close_releases_queued_bytes_after_every_producer_terminal_path_without_gc() {
    Python::initialize();
    Python::attach(|py| {
        for terminal in [
            ProducerTermination::Finish,
            ProducerTermination::EmptyFinal,
            ProducerTermination::Fail,
            ProducerTermination::FailNowait,
        ] {
            let budget = Arc::new(UploadBodyBudget::new(4));
            let raw = upload(py, &budget).unwrap();
            let recovery = upload(py, &budget).unwrap();
            assert!(raw.send_nowait(b"held"));
            match terminal {
                ProducerTermination::Finish => raw.finish(),
                ProducerTermination::EmptyFinal => assert!(raw.send_final_nowait(b"")),
                ProducerTermination::Fail => raw.fail(py, "provider failed".to_owned()).unwrap(),
                ProducerTermination::FailNowait => {
                    assert!(raw.fail_nowait("provider failed".to_owned()));
                }
            }
            assert!(raw.is_closed());
            assert_eq!(raw.account.buffered_bytes(), 4);
            assert_eq!(budget.buffered_bytes(), 4);
            assert!(!recovery.send_nowait(b"next"));
            assert_eq!(recovery.account.buffered_bytes(), 0);

            raw.close();
            assert_eq!(raw.account.buffered_bytes(), 0);
            assert_eq!(budget.buffered_bytes(), 0);
            assert!(recovery.send_final_nowait(b"next"));
            assert_eq!(recovery.account.buffered_bytes(), 4);
            assert_eq!(budget.buffered_bytes(), 4);
            raw.close();
            assert_eq!(budget.buffered_bytes(), 4);
            recovery.close();
            assert_eq!(recovery.account.buffered_bytes(), 0);
            assert_eq!(budget.buffered_bytes(), 0);
            raw.close();
            recovery.close();
            assert_eq!(budget.buffered_bytes(), 0);
        }
    });
}

async fn byte_admission_reached(budget: &UploadBodyBudget) {
    tokio::time::timeout(WATCHDOG, async {
        while budget.waiting_channels() == 0 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("raw sender did not enter byte admission");
}

async fn verify_recovery(acquire: &AcquireGate, budget: &Arc<UploadBodyBudget>) {
    let permit = tokio::time::timeout(WATCHDOG, acquire.acquire(ORIGIN, 1.0, 0))
        .await
        .unwrap()
        .unwrap();
    let (raw, receiver, content_length) = Python::attach(|py| {
        let raw = upload(py, budget).unwrap();
        assert!(raw.send_final(py, b"done").unwrap());
        let (receiver, content_length) = raw.take_receiver(py).unwrap();
        (raw, receiver, content_length)
    });
    let (body, completion) = streaming_request_body(receiver, content_length, None);
    let payload = tokio::time::timeout(WATCHDOG, body.collect())
        .await
        .unwrap()
        .unwrap()
        .to_bytes();
    assert_eq!(payload, b"done".as_slice());
    drop(payload);
    completion.mark_transport_flushed();
    assert!(completion.is_complete());
    assert_eq!(raw.account.buffered_bytes(), 0);
    assert_eq!(budget.buffered_bytes(), 0);
    drop(permit);
}

#[test]
fn write_timeout_closes_raw_sender_waiting_for_bytes_with_queue_slots_available() {
    Python::initialize();
    let runtime = Builder::new_current_thread().enable_time().build().unwrap();
    runtime.block_on(async {
        let metrics = Arc::new(Metrics::default());
        let acquire = AcquireGate::new(1, None, 1, Arc::clone(&metrics));
        let permit = acquire.acquire(ORIGIN, 1.0, 0).await.unwrap();
        let budget = Arc::new(UploadBodyBudget::new(8));
        let (raw, receiver, content_length) = Python::attach(|py| {
            let raw = upload(py, &budget).unwrap();
            assert!(raw.send_nowait(b"held"));
            let (receiver, content_length) = raw.take_receiver(py).unwrap();
            (raw, receiver, content_length)
        });
        let timeout = 0.025_f64;
        let write_timeout = RequestWriteTimeoutContext::new(
            Duration::from_secs_f64(timeout),
            timeout,
            ORIGIN.to_owned(),
            2,
        );
        let (mut body, completion) =
            streaming_request_body(receiver, content_length, Some(write_timeout));
        let retained = body.frame().await.unwrap().unwrap().into_data().unwrap();
        assert_eq!(retained, b"held".as_slice());
        let (result, worker) = start_blocked_send(&raw);
        byte_admission_reached(&budget).await;
        assert_eq!(raw.account.buffered_bytes(), 4);
        assert_eq!(budget.buffered_bytes(), 4);
        assert_eq!(result.try_recv(), Err(mpsc::TryRecvError::Empty));

        let error = tokio::time::timeout(WATCHDOG, body.frame())
            .await
            .unwrap()
            .unwrap()
            .unwrap_err();
        let diagnostic = request_write_timeout_from_error(error.as_ref()).unwrap();
        assert_eq!(diagnostic.timeout().to_bits(), timeout.to_bits());
        assert_eq!(diagnostic.origin(), ORIGIN);
        assert_eq!(diagnostic.redirect_hop(), 2);
        assert!(completion.write_timeout().is_some());
        assert!(!completion.is_complete());
        drop(body);
        assert!(!result.recv_timeout(WATCHDOG).unwrap());
        worker.join().unwrap();
        assert!(raw.is_closed());
        assert_eq!(budget.buffered_bytes(), 4);
        drop(retained);
        assert_eq!(raw.account.buffered_bytes(), 0);
        assert_eq!(budget.buffered_bytes(), 0);
        drop(permit);
        assert_eq!(metrics.snapshot().active_requests, 0);
        assert_eq!(metrics.snapshot().pending_requests, 0);
        verify_recovery(&acquire, &budget).await;
        assert_eq!(metrics.snapshot().active_requests, 0);
        assert_eq!(metrics.snapshot().pending_requests, 0);
    });
}

enum Cancellation {
    PythonFuture,
    ClientRegistry,
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

#[test]
fn python_cancellation_and_registry_close_release_blocked_native_upload_without_gc() {
    Python::initialize();
    let runtime = Builder::new_current_thread().enable_time().build().unwrap();
    for cancellation in [Cancellation::PythonFuture, Cancellation::ClientRegistry] {
        runtime.block_on(async {
            let metrics = Arc::new(Metrics::default());
            let acquire = AcquireGate::new(1, None, 1, Arc::clone(&metrics));
            let permit = acquire.acquire(ORIGIN, 1.0, 0).await.unwrap();
            let budget = Arc::new(UploadBodyBudget::new(8));
            let (raw, receiver, content_length) = Python::attach(|py| {
                let raw = upload(py, &budget).unwrap();
                assert!(raw.send_nowait(b"held"));
                let (receiver, content_length) = raw.take_receiver(py).unwrap();
                (raw, receiver, content_length)
            });
            let (mut body, _body_completion) =
                streaming_request_body(receiver, content_length, None);
            let retained = body.frame().await.unwrap().unwrap().into_data().unwrap();
            let (result, worker) = start_blocked_send(&raw);
            let task = tokio::spawn(async move {
                let _permit = permit;
                body.frame().await
            });
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
            byte_admission_reached(&budget).await;
            assert_eq!(metrics.snapshot().active_requests, 1);
            assert_eq!(metrics.snapshot().pending_requests, 0);
            assert_eq!(raw.account.buffered_bytes(), 4);
            assert_eq!(result.try_recv(), Err(mpsc::TryRecvError::Empty));
            match cancellation {
                Cancellation::PythonFuture => Python::attach(|py| {
                    python_loop.future.bind(py).call_method0("cancel").unwrap();
                }),
                Cancellation::ClientRegistry => registry.abort_all(),
            }
            python_loop.drain();
            let cancelled = tokio::time::timeout(WATCHDOG, task).await.unwrap();
            assert!(cancelled.is_err_and(|error| error.is_cancelled()));
            assert!(!result.recv_timeout(WATCHDOG).unwrap());
            worker.join().unwrap();
            assert!(!completion.finish());
            assert!(raw.is_closed());
            assert_eq!(budget.buffered_bytes(), 4);
            assert_eq!(metrics.snapshot().failed_requests, 1);
            assert_eq!(metrics.snapshot().active_requests, 0);
            assert_eq!(metrics.snapshot().pending_requests, 0);
            drop(retained);
            assert_eq!(raw.account.buffered_bytes(), 0);
            assert_eq!(budget.buffered_bytes(), 0);
            registry.abort_all();
            python_loop.drain();
            assert_eq!(metrics.snapshot().failed_requests, 1);
            verify_recovery(&acquire, &budget).await;
            assert_eq!(metrics.snapshot().active_requests, 0);
            assert_eq!(metrics.snapshot().pending_requests, 0);
        });
    }
}
