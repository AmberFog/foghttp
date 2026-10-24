use super::super::decode_response_body;
use super::super::test_control::{DecodeCheckpointTarget, DecodeTestControl};
use crate::core::metrics::Metrics;
use crate::core::response::{response_body_decoding_plan, BufferedBodyBudget, CollectedBody};
use crate::errors::FogHttpTimeoutError;
use crate::messages::REQUEST_TOTAL_TIMEOUT;
use crate::py::client::transport::context::RawResponseContext;
use hyper::header::CONTENT_ENCODING;
use hyper::HeaderMap;
use pyo3::prelude::*;
use std::future::Future;
use std::io::Write;
use std::sync::Arc;
use std::task::{Context, Waker};
use std::time::Instant;
use tokio::runtime::Builder;

#[test]
fn suspended_decoders_are_bounded_before_codec_work() {
    let runtime = Builder::new_current_thread().enable_time().build().unwrap();
    let payload = vec![b'x'; 256 * 1024];
    let mut compressor = brotli::CompressorWriter::new(Vec::new(), 8192, 1, 24);
    compressor.write_all(&payload).unwrap();
    compressor.flush().unwrap();
    let encoded = compressor.into_inner();
    runtime.block_on(async {
        let metrics = Arc::new(Metrics::default());
        let budget = BufferedBodyBudget::new(Some(1024 * 1024), Arc::clone(&metrics));
        let (control, _reached, _release) =
            DecodeTestControl::new(DecodeCheckpointTarget::Output {
                layer: 0,
                minimum: 0,
            });
        let context = RawResponseContext {
            started: Instant::now(),
            total_timeout: 30.0,
            read_timeout: 10.0,
            max_response_body_size: Some(payload.len()),
            buffered_body_budget: budget,
            buffered_decoders: Arc::new(tokio::sync::Semaphore::new(1)),
            origin: "http://collected.example",
            redirect_hop: 0,
            decode_checkpoint: Some(&control),
        };
        let mut headers = HeaderMap::new();
        headers.insert(CONTENT_ENCODING, "br".parse().unwrap());
        let mut decoders = Vec::new();
        let mut task_context = Context::from_waker(Waker::noop());
        for _ in 0..3 {
            let mut reservation = context.buffered_body_budget.start_response();
            reservation.reserve_chunk(encoded.len()).unwrap();
            let mut decoder = Box::pin(decode_response_body(
                CollectedBody {
                    content: encoded.clone(),
                    reservation,
                },
                response_body_decoding_plan(&headers),
                &context,
            ));
            assert!(decoder.as_mut().poll(&mut task_context).is_pending());
            decoders.push(decoder);
        }
        assert_eq!(
            control.visits(),
            1,
            "waiting decoders must not allocate codec workspace"
        );
        let reserved = metrics.snapshot().buffered_response_bytes;
        drop(decoders.remove(1));
        assert_eq!(
            metrics.snapshot().buffered_response_bytes,
            reserved - encoded.len()
        );
        assert_eq!(context.buffered_decoders.available_permits(), 0);
        drop(decoders.remove(0));
        assert!(decoders[0].as_mut().poll(&mut task_context).is_pending());
        assert_eq!(
            control.visits(),
            2,
            "cancelled waiter must not consume the released slot"
        );
        drop(decoders);
        assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
        assert_eq!(context.buffered_decoders.available_permits(), 1);
    });
}

fn collected(content: Vec<u8>, budget: &BufferedBodyBudget) -> CollectedBody {
    let mut reservation = budget.start_response();
    reservation.reserve_chunk(content.len()).unwrap();
    CollectedBody {
        content,
        reservation,
    }
}

fn response_context(budget: BufferedBodyBudget) -> RawResponseContext<'static> {
    RawResponseContext {
        started: Instant::now(),
        total_timeout: 30.0,
        read_timeout: 0.0,
        max_response_body_size: Some(1024 * 1024),
        buffered_body_budget: budget,
        buffered_decoders: Arc::new(tokio::sync::Semaphore::new(1)),
        origin: "http://collected.example",
        redirect_hop: 3,
        decode_checkpoint: None,
    }
}

#[test]
fn queued_decoder_uses_original_total_and_releases_body_without_codec_work() {
    Python::initialize();
    let runtime = Builder::new_current_thread().enable_time().build().unwrap();
    runtime.block_on(async {
        let metrics = Arc::new(Metrics::default());
        let budget = BufferedBodyBudget::new(None, Arc::clone(&metrics));
        let mut context = response_context(budget);
        context.total_timeout = 1.0;
        let held = context.buffered_decoders.acquire().await.unwrap();
        let (control, _reached, _release) =
            DecodeTestControl::new(DecodeCheckpointTarget::Output {
                layer: 0,
                minimum: 0,
            });
        context.decode_checkpoint = Some(&control);
        let mut headers = HeaderMap::new();
        headers.insert(CONTENT_ENCODING, "br".parse().unwrap());
        let mut decode = Box::pin(decode_response_body(
            collected(vec![0xff; 16], &context.buffered_body_budget),
            response_body_decoding_plan(&headers),
            &context,
        ));
        assert!(decode
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()))
            .is_pending());
        assert_eq!(control.visits(), 0);
        let result = tokio::time::timeout(super::test_fixtures::WATCHDOG, decode)
            .await
            .unwrap();
        let Err(error) = result else {
            panic!("queued decode outlived total")
        };
        Python::attach(|py| {
            assert!(error.get_type(py).is(py.get_type::<FogHttpTimeoutError>()));
            let args: (String, String, f64, f64, String, usize) =
                error.value(py).getattr("args").unwrap().extract().unwrap();
            assert_eq!(args.0, REQUEST_TOTAL_TIMEOUT);
            assert_eq!(args.1, "response_body");
            assert!(args.2 >= 1.0);
            assert_eq!(args.3.to_bits(), 1.0_f64.to_bits());
            assert_eq!(args.4, context.origin);
            assert_eq!(args.5, 3);
        });
        assert_eq!(control.visits(), 0);
        assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
        assert_eq!(context.buffered_decoders.available_permits(), 0);
        drop(held);
        assert_eq!(context.buffered_decoders.available_permits(), 1);
    });
}

#[test]
fn successful_and_failed_decode_release_admission_for_next_response() {
    Python::initialize();
    let runtime = Builder::new_current_thread().enable_time().build().unwrap();
    runtime.block_on(async {
        let metrics = Arc::new(Metrics::default());
        let context = response_context(BufferedBodyBudget::new(None, Arc::clone(&metrics)));
        let mut headers = HeaderMap::new();
        headers.insert(CONTENT_ENCODING, "gzip".parse().unwrap());
        for valid in [false, true, false, true] {
            let bytes = if valid {
                super::test_fixtures::gzip(b"healthy")
            } else {
                vec![0xff; 16]
            };
            let response = decode_response_body(
                collected(bytes, &context.buffered_body_budget),
                response_body_decoding_plan(&headers),
                &context,
            )
            .await;
            assert_eq!(response.is_ok(), valid);
            assert_eq!(context.buffered_decoders.available_permits(), 1);
            if let Ok(body) = &response {
                assert_eq!(body.content, b"healthy");
            }
            drop(response);
            assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
        }
    });
}
