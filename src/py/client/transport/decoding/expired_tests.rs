use super::decode_response_body;
use crate::core::metrics::Metrics;
use crate::core::response::{response_body_decoding_plan, BufferedBodyBudget, CollectedBody};
use crate::errors::FogHttpTimeoutError;
use crate::messages::REQUEST_TOTAL_TIMEOUT;
use crate::py::client::transport::context::RawResponseContext;
use flate2::{write::GzEncoder, Compression};
use hyper::header::CONTENT_ENCODING;
use hyper::HeaderMap;
use pyo3::prelude::*;
use std::io::Write;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::runtime::Builder;

#[test]
fn expired_original_total_rejects_fully_collected_compressed_body_and_releases_budget() {
    Python::initialize();
    let metrics = Arc::new(Metrics::default());
    let payload = b"collected buffered content ".repeat(2048);
    let mut compressor = GzEncoder::new(Vec::new(), Compression::fast());
    compressor.write_all(&payload).unwrap();
    let encoded = compressor.finish().unwrap();
    let budget = BufferedBodyBudget::new(Some(payload.len() * 2), Arc::clone(&metrics));
    let mut reservation = budget.start_response();
    reservation.reserve_chunk(encoded.len()).unwrap();
    assert_eq!(metrics.snapshot().buffered_response_bytes, encoded.len());
    let collected = CollectedBody {
        content: encoded,
        reservation,
    };
    let started = Instant::now().checked_sub(Duration::from_secs(2)).unwrap();
    let context = RawResponseContext {
        started,
        total_timeout: 1.0,
        read_timeout: 10.0,
        max_response_body_size: Some(payload.len()),
        buffered_body_budget: budget,
        buffered_decoders: Arc::new(tokio::sync::Semaphore::new(1)),
        origin: "http://collected.example",
        redirect_hop: 2,
        decode_checkpoint: None,
    };
    let mut headers = HeaderMap::new();
    headers.insert(CONTENT_ENCODING, "gzip".parse().unwrap());
    let runtime = Builder::new_current_thread().enable_time().build().unwrap();

    let result = runtime.block_on(decode_response_body(
        collected,
        response_body_decoding_plan(&headers),
        &context,
    ));

    let error = match result {
        Ok(response) => {
            assert_eq!(response.content, payload);
            drop(response);
            panic!("buffered decoding returned success after the original total deadline");
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
        assert!(
            args.2 >= 2.0,
            "diagnostic must retain the original request start"
        );
        assert_eq!(args.3.to_bits(), 1.0_f64.to_bits());
        assert_eq!(args.4, context.origin);
        assert_eq!(args.5, context.redirect_hop);
    });
    assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
    assert_eq!(metrics.snapshot().buffered_response_budget_rejections, 0);
}
