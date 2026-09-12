use super::{content_coding_plan, decoded_response_headers, ContentCoding, ContentCodingPlan};
use super::{
    decode_body, decode_content_coding, decode_deflate, decode_reader, response_body_decoding_plan,
    CollectedBody,
};
use crate::core::metrics::Metrics;
use crate::core::response::{BufferedBodyBudget, ResponseBodyError};
use flate2::write::{DeflateEncoder, ZlibEncoder};
use flate2::Compression;
use hyper::header::{HeaderValue, CONTENT_ENCODING};
use hyper::HeaderMap;
use std::error::Error;
use std::io::{self, Cursor, Read, Write};
use std::sync::Arc;

fn content_encoding_headers(values: &[&'static str]) -> HeaderMap {
    let mut headers = HeaderMap::new();
    for value in values {
        headers.append(CONTENT_ENCODING, HeaderValue::from_static(value));
    }
    headers
}

#[test]
fn content_coding_plan_supports_comma_separated_encodings() {
    let headers = content_encoding_headers(&["gzip, br"]);
    let plan = content_coding_plan(&headers);

    assert_eq!(
        plan,
        ContentCodingPlan::Decode(vec![ContentCoding::Gzip, ContentCoding::Brotli]),
    );
}

#[test]
fn content_coding_plan_preserves_multiple_header_field_order() {
    let headers = content_encoding_headers(&["gzip", "deflate"]);
    let plan = content_coding_plan(&headers);

    assert_eq!(
        plan,
        ContentCodingPlan::Decode(vec![ContentCoding::Gzip, ContentCoding::Deflate]),
    );
}

#[test]
fn content_coding_plan_leaves_unknown_encoding_untouched() {
    let headers = content_encoding_headers(&["zstd"]);
    let plan = content_coding_plan(&headers);

    assert_eq!(plan, ContentCodingPlan::LeaveEncoded);
}

#[test]
fn decode_bypass_preserves_content_headers_and_reservation_until_drop() {
    let content = b"opaque encoded response";
    let headers = vec![
        ("content-encoding".to_owned(), "zstd".to_owned()),
        ("content-length".to_owned(), content.len().to_string()),
        (
            "content-type".to_owned(),
            "application/octet-stream".to_owned(),
        ),
    ];
    let metrics = Arc::new(Metrics::default());
    let budget = BufferedBodyBudget::new(Some(content.len()), Arc::clone(&metrics));
    let mut reservation = budget.start_response();
    reservation.reserve_chunk(content.len()).unwrap();

    let response = decode_body(
        CollectedBody {
            content: content.to_vec(),
            reservation,
        },
        response_body_decoding_plan(&content_encoding_headers(&["zstd"])),
        Some(content.len()),
    )
    .expect("unsupported encoding remains opaque");

    assert_eq!(response.content, content);
    assert!(!response.decoded);
    assert_eq!(
        decoded_response_headers(headers.clone(), response.decoded),
        headers,
    );
    assert_eq!(metrics.snapshot().buffered_response_bytes, content.len());
    assert_eq!(metrics.snapshot().buffered_response_budget_rejections, 0);
    drop(response);
    assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
}

#[test]
fn decoded_response_headers_remove_consumed_body_headers() {
    let headers = decoded_response_headers(
        vec![
            ("content-type".to_owned(), "text/plain".to_owned()),
            ("content-encoding".to_owned(), "gzip".to_owned()),
            ("content-length".to_owned(), "42".to_owned()),
            ("x-trace".to_owned(), "abc".to_owned()),
        ],
        true,
    );

    assert_eq!(
        headers,
        vec![
            ("content-type".to_owned(), "text/plain".to_owned()),
            ("x-trace".to_owned(), "abc".to_owned()),
        ],
    );
}

#[test]
fn invalid_codings_retain_io_source_and_release_reserved_bytes() {
    for coding in [
        ContentCoding::Gzip,
        ContentCoding::Deflate,
        ContentCoding::Brotli,
    ] {
        let metrics = Arc::new(Metrics::default());
        let budget = BufferedBodyBudget::new(None, Arc::clone(&metrics));
        let mut reservation = budget.start_response();
        reservation.reserve_chunk(16).unwrap();
        let error = decode_content_coding(coding, &[0xff; 16], None, &mut reservation)
            .expect_err("invalid compressed body");
        assert!(
            matches!(&error, ResponseBodyError::Decode { coding: name, .. } if *name == super::content_coding_name(coding))
        );
        assert!(error.source().unwrap().is::<io::Error>());
        assert_eq!(metrics.snapshot().buffered_response_bytes, 16);
        drop(reservation);
        assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
    }
}

#[test]
fn raw_deflate_fallback_keeps_only_decoded_reservation() {
    let content = b"raw deflate response";
    let mut compressor = DeflateEncoder::new(Vec::new(), Compression::default());
    compressor.write_all(content).unwrap();
    let encoded = compressor.finish().unwrap();
    let metrics = Arc::new(Metrics::default());
    let budget = BufferedBodyBudget::new(None, Arc::clone(&metrics));
    let mut reservation = budget.start_response();
    reservation.reserve_chunk(encoded.len()).unwrap();
    let response = decode_body(
        CollectedBody {
            content: encoded,
            reservation,
        },
        response_body_decoding_plan(&content_encoding_headers(&["deflate"])),
        None,
    )
    .expect("raw deflate fallback");
    assert_eq!(response.content, content);
    assert!(response.decoded);
    assert_eq!(metrics.snapshot().buffered_response_bytes, content.len());
    drop(response);
    assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
}

#[test]
fn deflate_limits_do_not_fall_back_or_leak_attempt_bytes() {
    let content = vec![b'x'; super::DECODE_BUFFER_SIZE + 1];
    let mut compressor = ZlibEncoder::new(Vec::new(), Compression::default());
    compressor.write_all(&content).unwrap();
    let encoded = compressor.finish().unwrap();
    for size_limited in [true, false] {
        let metrics = Arc::new(Metrics::default());
        let budget_limit = encoded.len() + super::DECODE_BUFFER_SIZE;
        let budget = BufferedBodyBudget::new(
            (!size_limited).then_some(budget_limit),
            Arc::clone(&metrics),
        );
        let mut reservation = budget.start_response();
        reservation.reserve_chunk(encoded.len()).unwrap();
        let error = decode_deflate(
            &encoded,
            size_limited.then_some(super::DECODE_BUFFER_SIZE),
            &mut reservation,
        )
        .expect_err("decoded limit");
        if size_limited {
            assert!(
                matches!(error, ResponseBodyError::TooLarge { limit } if limit == super::DECODE_BUFFER_SIZE)
            );
            assert_eq!(metrics.snapshot().buffered_response_budget_rejections, 0);
        } else {
            assert!(
                matches!(error, ResponseBodyError::BudgetExceeded { limit } if limit == budget_limit)
            );
            assert_eq!(metrics.snapshot().buffered_response_budget_rejections, 1);
        }
        assert_eq!(metrics.snapshot().buffered_response_bytes, encoded.len());
        drop(reservation);
        assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
    }
}

struct FailedRead;

impl Read for FailedRead {
    fn read(&mut self, _buffer: &mut [u8]) -> io::Result<usize> {
        Err(io::Error::new(io::ErrorKind::InvalidData, "broken payload"))
    }
}

#[test]
fn decode_read_error_rolls_back_partial_output_and_preserves_source() {
    let metrics = Arc::new(Metrics::default());
    let budget = BufferedBodyBudget::new(None, Arc::clone(&metrics));
    let mut reservation = budget.start_response();
    reservation.reserve_chunk(7).unwrap();
    let error = decode_reader(
        ContentCoding::Gzip,
        Cursor::new(b"partial").chain(FailedRead),
        None,
        &mut reservation,
    )
    .unwrap_err();
    assert_eq!(
        error.to_string(),
        "failed to decode gzip response body: broken payload"
    );
    let source = error.source().unwrap().downcast_ref::<io::Error>().unwrap();
    assert_eq!(source.kind(), io::ErrorKind::InvalidData);
    assert_eq!(metrics.snapshot().buffered_response_bytes, 7);
    drop(reservation);
    assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
}
