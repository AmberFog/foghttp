use super::{content_coding_plan, decoded_response_headers, ContentCoding, ContentCodingPlan};
use super::{
    response_body_decoding_plan, BufferedBodyDecoder, BufferedDecodeStatus, CollectedBody,
    ResponseBody,
};
use crate::core::metrics::Metrics;
use crate::core::response::{BufferedBodyBudget, ResponseBodyError};
use flate2::write::{DeflateEncoder, ZlibEncoder};
use flate2::Compression;
use hyper::header::{HeaderValue, CONTENT_ENCODING};
use hyper::HeaderMap;
use std::error::Error;
use std::io::{self, Write};
use std::sync::Arc;

const MAX_TEST_STEPS: usize = 16_384;

fn run_decoder(decoder: &mut BufferedBodyDecoder) -> Result<(), ResponseBodyError> {
    for _ in 0..MAX_TEST_STEPS {
        if decoder.step()? == BufferedDecodeStatus::Finished {
            return Ok(());
        }
    }
    panic!("decode step guard exhausted: {:?}", decoder.test_progress());
}

fn decode_body(
    body: CollectedBody,
    plan: super::ResponseBodyDecodingPlan,
    limit: Option<usize>,
) -> Result<ResponseBody, ResponseBodyError> {
    let mut decoder = BufferedBodyDecoder::new(body, plan, limit);
    run_decoder(&mut decoder)?;
    decoder.finish()
}

fn coding_decoder(
    coding: ContentCoding,
    encoded: &[u8],
    limit: Option<usize>,
    budget: &BufferedBodyBudget,
) -> BufferedBodyDecoder {
    let mut reservation = budget.start_response();
    reservation.reserve_chunk(encoded.len()).unwrap();
    BufferedBodyDecoder::new(
        CollectedBody {
            content: encoded.to_vec(),
            reservation,
        },
        super::ResponseBodyDecodingPlan {
            plan: ContentCodingPlan::Decode(vec![coding]),
        },
        limit,
    )
}

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
        let mut decoder = coding_decoder(coding, &[0xff; 16], None, &budget);
        let error = run_decoder(&mut decoder).expect_err("invalid compressed body");
        assert!(
            matches!(&error, ResponseBodyError::Decode { coding: name, .. } if *name == coding.name())
        );
        assert!(error.source().unwrap().is::<io::Error>());
        assert_eq!(metrics.snapshot().buffered_response_bytes, 16);
        assert!(decoder.step().is_err());
        assert_eq!(metrics.snapshot().buffered_response_bytes, 16);
        drop(decoder);
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

fn deflate_payloads(content: &[u8]) -> [Vec<u8>; 2] {
    let mut zlib = ZlibEncoder::new(Vec::new(), Compression::default());
    zlib.write_all(content).unwrap();
    let mut raw = DeflateEncoder::new(Vec::new(), Compression::default());
    raw.write_all(content).unwrap();
    [zlib.finish().unwrap(), raw.finish().unwrap()]
}

fn assert_deflate_error_preserves_encoded_reservation(encoded: &[u8]) {
    let metrics = Arc::new(Metrics::default());
    let budget = BufferedBodyBudget::new(None, Arc::clone(&metrics));
    let mut decoder = coding_decoder(ContentCoding::Deflate, encoded, None, &budget);
    let error = run_decoder(&mut decoder).expect_err("incomplete deflate");
    assert!(matches!(
        error,
        ResponseBodyError::Decode {
            coding: "deflate",
            ..
        }
    ));
    assert!(error.source().unwrap().is::<io::Error>());
    assert_eq!(metrics.snapshot().buffered_response_bytes, encoded.len());
    assert_eq!(metrics.snapshot().buffered_response_budget_rejections, 0);
    drop(decoder);
    assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
}

#[test]
fn deflate_requires_stream_end_for_zlib_and_raw_payloads() {
    let content = vec![b'x'; super::DECODE_BUFFER_SIZE * 2 + 1];
    for encoded in deflate_payloads(&content) {
        assert_deflate_error_preserves_encoded_reservation(&encoded[..encoded.len() / 2]);
        assert_deflate_error_preserves_encoded_reservation(&encoded[..encoded.len() - 1]);
    }
}

#[test]
fn zlib_requires_present_and_valid_checksum() {
    let [mut encoded, _raw] = deflate_payloads(&vec![b'x'; super::DECODE_BUFFER_SIZE * 2 + 1]);
    assert_deflate_error_preserves_encoded_reservation(&encoded[..encoded.len() - 4]);
    let checksum_end = encoded.last_mut().unwrap();
    *checksum_end ^= 0xff;
    assert_deflate_error_preserves_encoded_reservation(&encoded);
}

#[test]
fn zlib_framing_errors_do_not_fall_back_to_complete_raw_streams() {
    let prefix = [
        0x78, 0x01, 0x00, 0xfe, 0xff, 0x01, 0x00, 0x00, 0x00, 0xff, 0xff, 0x01, 0x00, 0x00, 0xff,
        0xff,
    ];
    let dictionary_content = [b'x'; 32];
    let mut dictionary_stream = vec![0x78, 0x20, 0x00, 0xdf, 0xff];
    dictionary_stream.extend_from_slice(&dictionary_content);
    dictionary_stream.extend_from_slice(&[0x01, 0x00, 0x00, 0xff, 0xff]);

    for (encoded, content) in [
        (prefix.as_slice(), [0x01].as_slice()),
        (dictionary_stream.as_slice(), dictionary_content.as_slice()),
    ] {
        let mut decoder = flate2::Decompress::new(false);
        let mut output = [0; 64];
        let status = decoder
            .decompress(encoded, &mut output, flate2::FlushDecompress::None)
            .unwrap();
        assert_eq!(status, flate2::Status::StreamEnd);
        let produced = usize::try_from(decoder.total_out()).unwrap();
        assert_eq!(&output[..produced], content);
        assert_deflate_error_preserves_encoded_reservation(encoded);
    }
}

#[test]
fn complete_deflate_preserves_empty_and_buffer_boundary_payloads() {
    for size in [
        0,
        super::DECODE_BUFFER_SIZE,
        super::DECODE_BUFFER_SIZE * 2,
        super::DECODE_BUFFER_SIZE * 2 + 1,
    ] {
        let content = vec![b'x'; size];
        for encoded in deflate_payloads(&content) {
            let metrics = Arc::new(Metrics::default());
            let budget = BufferedBodyBudget::new(None, Arc::clone(&metrics));
            let mut decoder = coding_decoder(ContentCoding::Deflate, &encoded, Some(size), &budget);
            run_decoder(&mut decoder).expect("complete zlib/raw deflate at buffer boundary");
            let response = decoder.finish().unwrap();
            assert_eq!(response.content, content);
            assert!(response.decoded);
            assert_eq!(metrics.snapshot().buffered_response_bytes, size);
            drop(response);
            assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
        }
    }
}

#[test]
fn deflate_limits_do_not_fall_back_or_leak_attempt_bytes() {
    let content = vec![b'x'; super::DECODE_BUFFER_SIZE + 1];
    for encoded in deflate_payloads(&content) {
        for size_limited in [true, false] {
            let metrics = Arc::new(Metrics::default());
            let budget_limit = encoded.len() + super::DECODE_BUFFER_SIZE;
            let budget = BufferedBodyBudget::new(
                (!size_limited).then_some(budget_limit),
                Arc::clone(&metrics),
            );
            let mut decoder = coding_decoder(
                ContentCoding::Deflate,
                &encoded,
                size_limited.then_some(super::DECODE_BUFFER_SIZE),
                &budget,
            );
            let error = run_decoder(&mut decoder).expect_err("decoded limit");
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
            drop(decoder);
            assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
        }
    }
}

#[test]
fn decode_read_error_rolls_back_partial_output_and_preserves_source() {
    let mut random = fastrand::Rng::with_seed(346);
    let content = (0..super::DECODE_BUFFER_SIZE * 3)
        .map(|_| random.u8(..))
        .collect::<Vec<_>>();
    let [mut encoded, _raw] = deflate_payloads(&content);
    *encoded.last_mut().unwrap() ^= 0xff;
    let metrics = Arc::new(Metrics::default());
    let budget = BufferedBodyBudget::new(None, Arc::clone(&metrics));
    let mut decoder = coding_decoder(ContentCoding::Deflate, &encoded, None, &budget);
    let mut output_seen = false;
    let error = 'failed: {
        for _ in 0..MAX_TEST_STEPS {
            match decoder.step() {
                Ok(BufferedDecodeStatus::Progress) => {
                    output_seen |= decoder.test_progress().output_bytes > 0;
                }
                Ok(BufferedDecodeStatus::Finished) => panic!("corrupt checksum accepted"),
                Err(error) => break 'failed error,
            }
        }
        panic!(
            "checksum step guard exhausted: {:?}",
            decoder.test_progress()
        );
    };
    assert!(output_seen);
    let source = error.source().unwrap().downcast_ref::<io::Error>().unwrap();
    assert_eq!(source.kind(), io::ErrorKind::InvalidData);
    assert!(error
        .to_string()
        .starts_with("failed to decode deflate response body:"));
    assert_eq!(metrics.snapshot().buffered_response_bytes, encoded.len());
    assert!(decoder.step().is_err());
    assert_eq!(metrics.snapshot().buffered_response_bytes, encoded.len());
    drop(decoder);
    assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
}

fn gzip_payload(content: &[u8]) -> Vec<u8> {
    let mut writer = flate2::write::GzEncoder::new(Vec::new(), Compression::default());
    writer.write_all(content).unwrap();
    writer.finish().unwrap()
}

fn decoded_coding(coding: ContentCoding, encoded: &[u8]) -> Result<Vec<u8>, ResponseBodyError> {
    let budget = BufferedBodyBudget::new(None, Arc::new(Metrics::default()));
    let mut decoder = coding_decoder(coding, encoded, None, &budget);
    run_decoder(&mut decoder)?;
    Ok(decoder.finish()?.content)
}

#[test]
fn cooperative_gzip_preserves_reader_completion_and_members() {
    use std::io::Read;
    let content = vec![b'x'; super::DECODE_BUFFER_SIZE * 3 + 1];
    let encoded = gzip_payload(&content);
    let mut concat = encoded.clone();
    concat.extend_from_slice(&gzip_payload(b"second member"));
    let mut bad_crc = encoded.clone();
    let crc_index = bad_crc.len() - 8;
    bad_crc[crc_index] ^= 0xff;
    let mut trailing = encoded.clone();
    trailing.extend_from_slice(b"trailing data");
    let mut zero_padding = encoded.clone();
    zero_padding.extend_from_slice(&[0; 32]);
    for input in [
        Vec::new(),
        gzip_payload(b""),
        encoded.clone(),
        concat,
        encoded[..encoded.len() / 2].to_vec(),
        encoded[..encoded.len() - 1].to_vec(),
        bad_crc,
        trailing,
        zero_padding,
    ] {
        let mut previous = flate2::read::MultiGzDecoder::new(input.as_slice());
        let mut expected = Vec::new();
        let old = previous.read_to_end(&mut expected);
        let current = decoded_coding(ContentCoding::Gzip, &input);
        assert_eq!(
            current.is_ok(),
            old.is_ok(),
            "gzip input size {}",
            input.len()
        );
        if let Ok(current) = current {
            assert_eq!(current, expected);
        }
    }
}

#[test]
fn layer_and_raw_fallback_boundaries_return_before_more_codec_work() {
    let content = vec![b'x'; super::DECODE_BUFFER_SIZE * 3];
    let [_zlib, raw] = deflate_payloads(&content);
    let budget = BufferedBodyBudget::new(None, Arc::new(Metrics::default()));
    let mut decoder = coding_decoder(ContentCoding::Deflate, &raw, None, &budget);
    assert_eq!(decoder.step().unwrap(), BufferedDecodeStatus::Progress);
    let progress = decoder.test_progress();
    assert!(progress.raw_deflate);
    assert_eq!(progress.output_bytes, 0);
    assert_eq!(decoder.layer.as_ref().unwrap().offset, 0);
    run_decoder(&mut decoder).unwrap();
    assert_eq!(decoder.finish().unwrap().content, content);

    let encoded = gzip_payload(&gzip_payload(&content));
    let mut reservation = budget.start_response();
    reservation.reserve_chunk(encoded.len()).unwrap();
    let mut decoder = BufferedBodyDecoder::new(
        CollectedBody {
            content: encoded,
            reservation,
        },
        response_body_decoding_plan(&content_encoding_headers(&["gzip, gzip"])),
        None,
    );
    for _ in 0..MAX_TEST_STEPS {
        if decoder.test_progress().completed_layers != 0 {
            break;
        }
        assert_eq!(decoder.step().unwrap(), BufferedDecodeStatus::Progress);
    }
    let progress = decoder.test_progress();
    assert_eq!(
        progress.completed_layers, 1,
        "layer step guard exhausted: {progress:?}"
    );
    assert_eq!(progress.remaining_layers, 1);
    assert_eq!(progress.output_bytes, 0);
    assert!(decoder.layer.is_none());
    run_decoder(&mut decoder).unwrap();
    assert_eq!(decoder.finish().unwrap().content, content);
}

#[test]
fn buffered_codings_keep_unlimited_layer_count() {
    let content = b"six layers remain valid";
    let mut encoded = content.to_vec();
    for _ in 0..6 {
        encoded = gzip_payload(&encoded);
    }
    let budget = BufferedBodyBudget::new(None, Arc::new(Metrics::default()));
    let mut reservation = budget.start_response();
    reservation.reserve_chunk(encoded.len()).unwrap();
    let response = decode_body(
        CollectedBody {
            content: encoded,
            reservation,
        },
        response_body_decoding_plan(&content_encoding_headers(&[
            "gzip,gzip,gzip,gzip,gzip,gzip",
        ])),
        None,
    )
    .unwrap();
    assert_eq!(response.content, content);
}

#[test]
fn buffered_brotli_keeps_large_window_and_trailing_compatibility() {
    let content = vec![0x5a; 128 * 1024];
    let params = brotli::enc::BrotliEncoderParams {
        quality: 4,
        lgwin: 25,
        large_window: true,
        ..Default::default()
    };
    let mut encoded = Vec::new();
    brotli::BrotliCompress(&mut content.as_slice(), &mut encoded, &params).unwrap();
    encoded.extend_from_slice(b"trailing bytes remain ignored");
    assert_eq!(
        decoded_coding(ContentCoding::Brotli, &encoded).unwrap(),
        content
    );
}

#[test]
fn nonfinal_brotli_block_retains_workspace_beyond_body_reservation() {
    let content = vec![b'x'; 256 * 1024];
    let mut compressor = brotli::CompressorWriter::new(Vec::new(), 8192, 1, 24);
    compressor.write_all(&content).unwrap();
    compressor.flush().unwrap();
    let encoded = compressor.into_inner();
    let metrics = Arc::new(Metrics::default());
    let budget = BufferedBodyBudget::new(Some(1024 * 1024), Arc::clone(&metrics));
    let mut decoder = coding_decoder(ContentCoding::Brotli, &encoded, None, &budget);
    assert_eq!(decoder.step().unwrap(), BufferedDecodeStatus::Progress);
    let super::Codec::Brotli(state) = &decoder.layer.as_ref().unwrap().codec else {
        panic!("expected Brotli codec");
    };
    assert_eq!(state.ringbuffer_size, 1 << 24);
    assert!(metrics.snapshot().buffered_response_bytes < 1024 * 1024);
    run_decoder(&mut decoder).unwrap();
    assert_eq!(decoder.finish().unwrap().content, content);
    assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
}

#[test]
fn cooperative_readers_preserve_truncation_and_output_limit_precedence() {
    use std::io::Read;
    let content = vec![b'x'; 3 * super::DECODE_BUFFER_SIZE + 1];
    let mut br = brotli::CompressorWriter::new(Vec::new(), 8192, 4, 22);
    br.write_all(&content).unwrap();
    let br = br.into_inner();
    for (coding, encoded) in [
        (ContentCoding::Gzip, gzip_payload(&content)),
        (ContentCoding::Brotli, br),
    ] {
        for length in [0, encoded.len() / 2, encoded.len() - 1, encoded.len()] {
            let encoded = &encoded[..length];
            for limit in [
                0,
                super::DECODE_BUFFER_SIZE,
                content.len(),
                content.len() + 1,
            ] {
                let mut reader: Box<dyn Read> = match coding {
                    ContentCoding::Gzip => Box::new(flate2::read::MultiGzDecoder::new(encoded)),
                    ContentCoding::Brotli => Box::new(brotli::Decompressor::new(encoded, 8192)),
                    ContentCoding::Deflate => unreachable!(),
                };
                let mut expected = Vec::new();
                let mut buffer = [0; super::DECODE_BUFFER_SIZE];
                let old = 'reference: {
                    for _ in 0..MAX_TEST_STEPS {
                        match reader.read(&mut buffer) {
                            Err(_) => break 'reference Err("decode"),
                            Ok(0) => break 'reference Ok(expected),
                            Ok(read) => {
                                if expected.len() + read > limit {
                                    break 'reference Err("limit");
                                }
                                expected.extend_from_slice(&buffer[..read]);
                            }
                        }
                    }
                    panic!("reference read guard exhausted: {coding:?}, input={length}, output={}, limit={limit}", expected.len());
                };
                let budget = BufferedBodyBudget::new(None, Arc::new(Metrics::default()));
                let mut decoder = coding_decoder(coding, encoded, Some(limit), &budget);
                let current = run_decoder(&mut decoder)
                    .map(|()| decoder.finish().unwrap().content)
                    .map_err(|error| match error {
                        ResponseBodyError::TooLarge { .. } => "limit",
                        ResponseBodyError::Decode { .. } => "decode",
                        _ => panic!("unexpected codec error"),
                    });
                assert_eq!(current, old, "{coding:?}, input={length}, limit={limit}");
            }
        }
    }
}

#[test]
fn deflate_preserves_trailing_compatibility_without_extra_fallback() {
    for mut encoded in deflate_payloads(b"trailing bytes remain ignored") {
        encoded.extend_from_slice(b"trailing bytes");
        assert_eq!(
            decoded_coding(ContentCoding::Deflate, &encoded).unwrap(),
            b"trailing bytes remain ignored"
        );
    }
}
