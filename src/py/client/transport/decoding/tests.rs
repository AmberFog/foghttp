#[path = "admission_tests.rs"]
mod admission_tests;
#[path = "expired_tests.rs"]
mod expired_tests;
#[path = "test_fixtures.rs"]
mod test_fixtures;

#[path = "compatibility_tests.rs"]
mod compatibility_tests;
#[path = "native_cases.rs"]
mod native_cases;
#[path = "native_test_support.rs"]
mod native_test_support;
#[path = "registry_tests.rs"]
mod registry_tests;

use super::decode_response_body;

use super::test_control::DecodeCheckpointTarget;
use crate::core::response::BufferedDecodeStatus;
use crate::errors::FogHttpTimeoutError;
use crate::messages::REQUEST_TOTAL_TIMEOUT;
use pyo3::prelude::*;
use std::time::Duration;
use test_fixtures::{controlled_decode, reach_checkpoint, ControlledDecode, BODY_SIZE, WATCHDOG};
use tokio::runtime::Builder;

#[test]
fn original_total_expires_at_output_layer_fallback_and_final_checkpoints() {
    Python::initialize();
    let runtime = Builder::new_current_thread().enable_time().build().unwrap();
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
            let ControlledDecode {
                control,
                reached,
                release,
                task,
                metrics,
                started,
            } = controlled_decode(target);
            let event = reach_checkpoint(reached).await;
            assert!(metrics.snapshot().buffered_response_bytes > 0);
            assert!(control.visits() > 0);
            if matches!(target, DecodeCheckpointTarget::Finished) {
                assert_eq!(event.status, BufferedDecodeStatus::Finished);
            }
            let visits = control.visits();
            tokio::time::sleep(Duration::from_secs(1).saturating_sub(started.elapsed())).await;
            release.send(()).unwrap();
            let result = tokio::time::timeout(WATCHDOG, task).await.unwrap().unwrap();
            let error = match result {
                Ok(body) => {
                    drop(body);
                    panic!("success after shared total expired at {target:?}");
                }
                Err(error) => error,
            };
            Python::attach(|python| {
                assert!(error
                    .get_type(python)
                    .is(python.get_type::<FogHttpTimeoutError>()));
                let args: (String, String, f64, f64, String, usize) = error
                    .value(python)
                    .getattr("args")
                    .unwrap()
                    .extract()
                    .unwrap();
                assert_eq!(args.0, REQUEST_TOTAL_TIMEOUT);
                assert_eq!(args.1, "response_body");
                assert!(args.2 >= 1.0);
                assert_eq!(args.3.to_bits(), 1.0_f64.to_bits());
                assert_eq!(args.4, "http://collected.example");
                assert_eq!(args.5, 3);
            });
            assert_eq!(
                control.visits(),
                visits,
                "no codec call after timeout checkpoint"
            );
            assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
            assert_eq!(metrics.snapshot().buffered_response_budget_rejections, 0);
        });
    }
}

#[test]
fn aborting_post_eof_decode_stops_work_and_drops_native_reservations() {
    let runtime = Builder::new_current_thread().enable_time().build().unwrap();
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
            let ControlledDecode {
                control,
                reached,
                release,
                task,
                metrics,
                ..
            } = controlled_decode(target);
            let event = reach_checkpoint(reached).await;
            assert!(event.progress.output_bytes <= BODY_SIZE);
            assert!(metrics.snapshot().buffered_response_bytes > 0);
            let visits = control.visits();
            task.abort();
            let result = tokio::time::timeout(WATCHDOG, task).await.unwrap();
            let Err(error) = result else {
                panic!("aborted native task unexpectedly completed")
            };
            assert!(error.is_cancelled());
            assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
            release
                .send(())
                .expect_err("aborted future must have dropped checkpoint receiver");
            tokio::task::yield_now().await;
            assert_eq!(
                control.visits(),
                visits,
                "aborted decode resumed work after quiescence"
            );
        });
    }
}

#[test]
fn decoder_yields_without_network_wait_and_drop_releases_content_reservations() {
    use crate::core::metrics::Metrics;
    use crate::core::response::{response_body_decoding_plan, BufferedBodyBudget, CollectedBody};
    use crate::py::client::transport::context::RawResponseContext;
    use hyper::header::CONTENT_ENCODING;
    use hyper::HeaderMap;
    use std::future::Future;
    use std::sync::Arc;
    use std::task::{Context, Poll, Waker};
    use std::time::Instant;

    let runtime = Builder::new_current_thread().enable_time().build().unwrap();
    runtime.block_on(async {
        let metrics = Arc::new(Metrics::default());
        let encoded_payload = test_fixtures::gzip(&test_fixtures::BODY);
        let budget = BufferedBodyBudget::new(Some(BODY_SIZE * 4), Arc::clone(&metrics));
        let mut reservation = budget.start_response();
        reservation.reserve_chunk(encoded_payload.len()).unwrap();
        let collected = CollectedBody {
            content: encoded_payload,
            reservation,
        };
        let mut headers = HeaderMap::new();
        headers.insert(CONTENT_ENCODING, "gzip".parse().unwrap());
        let context = RawResponseContext {
            started: Instant::now(),
            total_timeout: 30.0,
            read_timeout: 10.0,
            max_response_body_size: Some(BODY_SIZE),
            buffered_body_budget: budget,
            buffered_decoders: Arc::new(tokio::sync::Semaphore::new(1)),
            origin: "http://collected.example",
            redirect_hop: 0,
            decode_checkpoint: None,
        };
        let mut decode = Box::pin(decode_response_body(
            collected,
            response_body_decoding_plan(&headers),
            &context,
        ));
        let mut task_context = Context::from_waker(Waker::noop());
        assert!(matches!(
            decode.as_mut().poll(&mut task_context),
            Poll::Pending
        ));
        assert!(metrics.snapshot().buffered_response_bytes > 0);
        drop(decode);
        assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
    });
}
