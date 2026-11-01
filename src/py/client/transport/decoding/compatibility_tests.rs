use super::super::decode_response_body;
use super::test_fixtures::gzip;
use crate::core::metrics::Metrics;
use crate::core::response::{response_body_decoding_plan, BufferedBodyBudget, CollectedBody};
use crate::py::client::transport::context::RawResponseContext;
use hyper::header::CONTENT_ENCODING;
use hyper::HeaderMap;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::runtime::Builder;

#[test]
fn identity_and_unknown_codings_preserve_opaque_body_without_codec_deadline_checkpoints() {
    let runtime = Builder::new_current_thread().enable_time().build().unwrap();
    for coding in ["identity", "zstd", "gzip,zstd"] {
        let metrics = Arc::new(Metrics::default());
        let payload = b"opaque content".to_vec();
        let budget = BufferedBodyBudget::new(Some(payload.len()), Arc::clone(&metrics));
        let mut reservation = budget.start_response();
        reservation.reserve_chunk(payload.len()).unwrap();
        let collected = CollectedBody {
            content: payload.clone(),
            reservation,
        };
        let mut headers = HeaderMap::new();
        headers.insert(CONTENT_ENCODING, coding.parse().unwrap());
        let context = RawResponseContext {
            started: Instant::now().checked_sub(Duration::from_secs(2)).unwrap(),
            total_timeout: 1.0,
            read_timeout: 0.0,
            max_response_body_size: Some(payload.len()),
            buffered_body_budget: budget,
            buffered_decoders: Arc::new(tokio::sync::Semaphore::new(0)),
            origin: "http://collected.example",
            redirect_hop: 0,
            decode_checkpoint: None,
        };
        let response = runtime
            .block_on(decode_response_body(
                collected,
                response_body_decoding_plan(&headers),
                &context,
            ))
            .unwrap();
        assert_eq!(response.content, payload);
        assert!(!response.decoded);
        assert_eq!(metrics.snapshot().buffered_response_bytes, payload.len());
        drop(response);
        assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
    }
}

#[test]
fn buffered_decoding_uses_total_without_restarting_network_read_timeout() {
    let runtime = Builder::new_current_thread().enable_time().build().unwrap();
    let metrics = Arc::new(Metrics::default());
    let payload = b"fully collected compressed content".repeat(2048);
    let encoded = gzip(&payload);
    let budget = BufferedBodyBudget::new(Some(payload.len() * 2), Arc::clone(&metrics));
    let mut reservation = budget.start_response();
    reservation.reserve_chunk(encoded.len()).unwrap();
    let collected = CollectedBody {
        content: encoded,
        reservation,
    };
    let mut headers = HeaderMap::new();
    headers.insert(CONTENT_ENCODING, "gzip".parse().unwrap());
    let context = RawResponseContext {
        started: Instant::now(),
        total_timeout: 30.0,
        read_timeout: 0.0,
        max_response_body_size: Some(payload.len()),
        buffered_body_budget: budget,
        buffered_decoders: Arc::new(tokio::sync::Semaphore::new(1)),
        origin: "http://collected.example",
        redirect_hop: 0,
        decode_checkpoint: None,
    };
    let response = runtime
        .block_on(decode_response_body(
            collected,
            response_body_decoding_plan(&headers),
            &context,
        ))
        .unwrap();
    assert_eq!(response.content, payload);
    assert!(response.decoded);
    drop(response);
    assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
}
