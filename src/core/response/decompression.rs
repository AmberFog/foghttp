use super::body::{enforce_response_body_limit, CollectedBody};
use super::ResponseBodyError;
use crate::core::headers::HeaderPairs;
use brotli::Decompressor;
use flate2::read::{DeflateDecoder, MultiGzDecoder, ZlibDecoder};
use hyper::header::CONTENT_ENCODING;
use hyper::HeaderMap;
use std::io::{Cursor, Read};

const DECODE_BUFFER_SIZE: usize = 8192;
const CONTENT_ENCODING_HEADER: &str = "content-encoding";
const CONTENT_LENGTH_HEADER: &str = "content-length";

pub struct ResponseBody {
    pub content: Vec<u8>,
    pub reservation: super::BufferedBodyReservation,
    pub decoded: bool,
}

pub struct ResponseBodyDecodingPlan {
    plan: ContentCodingPlan,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ContentCoding {
    Gzip,
    Deflate,
    Brotli,
}

#[derive(Debug, Eq, PartialEq)]
enum ContentCodingPlan {
    Decode(Vec<ContentCoding>),
    LeaveEncoded,
}

pub fn response_body_decoding_plan(headers: &HeaderMap) -> ResponseBodyDecodingPlan {
    ResponseBodyDecodingPlan {
        plan: content_coding_plan(headers),
    }
}

pub fn decode_body(
    collected: CollectedBody,
    decoding_plan: ResponseBodyDecodingPlan,
    max_response_body_size: Option<usize>,
) -> Result<ResponseBody, ResponseBodyError> {
    match decoding_plan.plan {
        ContentCodingPlan::Decode(codings) => {
            decode_supported_body(collected, codings.as_slice(), max_response_body_size)
        }
        ContentCodingPlan::LeaveEncoded => Ok(ResponseBody {
            content: collected.content,
            reservation: collected.reservation,
            decoded: false,
        }),
    }
}

pub fn decoded_response_headers(headers: HeaderPairs, decoded: bool) -> HeaderPairs {
    if !decoded {
        return headers;
    }

    headers
        .into_iter()
        .filter(|(name, _value)| !decoded_body_header(name))
        .collect()
}

fn content_coding_plan(headers: &HeaderMap) -> ContentCodingPlan {
    let mut codings = Vec::new();
    for value in &headers.get_all(CONTENT_ENCODING) {
        let Ok(value) = value.to_str() else {
            return ContentCodingPlan::LeaveEncoded;
        };
        for item in value.split(',') {
            let coding = item.trim().to_ascii_lowercase();
            if coding.is_empty() || coding == "identity" {
                continue;
            }
            let Some(supported) = supported_content_coding(&coding) else {
                return ContentCodingPlan::LeaveEncoded;
            };
            codings.push(supported);
        }
    }

    if codings.is_empty() {
        ContentCodingPlan::LeaveEncoded
    } else {
        ContentCodingPlan::Decode(codings)
    }
}

fn supported_content_coding(coding: &str) -> Option<ContentCoding> {
    match coding {
        "gzip" | "x-gzip" => Some(ContentCoding::Gzip),
        "deflate" => Some(ContentCoding::Deflate),
        "br" => Some(ContentCoding::Brotli),
        _unknown => None,
    }
}

fn decode_supported_body(
    mut body: CollectedBody,
    codings: &[ContentCoding],
    max_response_body_size: Option<usize>,
) -> Result<ResponseBody, ResponseBodyError> {
    let mut content = std::mem::take(&mut body.content);
    for coding in codings.iter().rev().copied() {
        let encoded_size = content.len();
        content = decode_content_coding(
            coding,
            &content,
            max_response_body_size,
            &mut body.reservation,
        )?;
        body.reservation.release_chunk(encoded_size)?;
    }

    Ok(ResponseBody {
        content,
        reservation: body.reservation,
        decoded: true,
    })
}

fn decode_content_coding(
    coding: ContentCoding,
    content: &[u8],
    max_response_body_size: Option<usize>,
    reservation: &mut super::BufferedBodyReservation,
) -> Result<Vec<u8>, ResponseBodyError> {
    match coding {
        ContentCoding::Gzip => decode_reader(
            coding,
            MultiGzDecoder::new(Cursor::new(content)),
            max_response_body_size,
            reservation,
        ),
        ContentCoding::Deflate => decode_deflate(content, max_response_body_size, reservation),
        ContentCoding::Brotli => decode_reader(
            coding,
            Decompressor::new(Cursor::new(content), DECODE_BUFFER_SIZE),
            max_response_body_size,
            reservation,
        ),
    }
}

fn decode_deflate(
    content: &[u8],
    max_response_body_size: Option<usize>,
    reservation: &mut super::BufferedBodyReservation,
) -> Result<Vec<u8>, ResponseBodyError> {
    match decode_reader_result(
        ZlibDecoder::new(Cursor::new(content)),
        max_response_body_size,
        reservation,
    ) {
        Ok(decoded) => Ok(decoded),
        Err(DecodeAttemptError::Read(_err)) => decode_reader(
            ContentCoding::Deflate,
            DeflateDecoder::new(Cursor::new(content)),
            max_response_body_size,
            reservation,
        ),
        Err(DecodeAttemptError::Runtime(err)) => Err(err),
    }
}

fn decode_reader<R: Read>(
    coding: ContentCoding,
    reader: R,
    max_response_body_size: Option<usize>,
    reservation: &mut super::BufferedBodyReservation,
) -> Result<Vec<u8>, ResponseBodyError> {
    decode_reader_result(reader, max_response_body_size, reservation)
        .map_err(|err| decode_attempt_error(coding, err))
}

enum DecodeAttemptError {
    Read(std::io::Error),
    Runtime(ResponseBodyError),
}

fn decode_reader_result<R: Read>(
    mut reader: R,
    max_response_body_size: Option<usize>,
    reservation: &mut super::BufferedBodyReservation,
) -> Result<Vec<u8>, DecodeAttemptError> {
    let mut decoded = Vec::new();
    let mut buffer = [0_u8; DECODE_BUFFER_SIZE];
    let mut attempt_reserved = 0_usize;

    loop {
        let read = match reader.read(&mut buffer) {
            Ok(read) => read,
            Err(err) => {
                if let Err(release_error) = reservation.release_chunk(attempt_reserved) {
                    return Err(DecodeAttemptError::Runtime(release_error));
                }
                return Err(DecodeAttemptError::Read(err));
            }
        };
        if read == 0 {
            return Ok(decoded);
        }

        if let Err(err) = enforce_response_body_limit(decoded.len(), read, max_response_body_size) {
            if let Err(release_error) = reservation.release_chunk(attempt_reserved) {
                return Err(DecodeAttemptError::Runtime(release_error));
            }
            return Err(DecodeAttemptError::Runtime(err));
        }
        if let Err(err) = reservation.reserve_chunk(read) {
            if let Err(release_error) = reservation.release_chunk(attempt_reserved) {
                return Err(DecodeAttemptError::Runtime(release_error));
            }
            return Err(DecodeAttemptError::Runtime(err));
        }
        let Some(next_attempt_reserved) = attempt_reserved.checked_add(read) else {
            if let Err(release_error) = reservation.release_chunk(attempt_reserved) {
                return Err(DecodeAttemptError::Runtime(release_error));
            }
            return Err(DecodeAttemptError::Runtime(
                ResponseBodyError::DecodeReservationOverflow,
            ));
        };
        attempt_reserved = next_attempt_reserved;
        decoded.extend_from_slice(&buffer[..read]);
    }
}

fn decode_attempt_error(coding: ContentCoding, err: DecodeAttemptError) -> ResponseBodyError {
    match err {
        DecodeAttemptError::Read(source) => ResponseBodyError::Decode {
            coding: content_coding_name(coding),
            source,
        },
        DecodeAttemptError::Runtime(err) => err,
    }
}

fn content_coding_name(coding: ContentCoding) -> &'static str {
    match coding {
        ContentCoding::Gzip => "gzip",
        ContentCoding::Deflate => "deflate",
        ContentCoding::Brotli => "br",
    }
}

fn decoded_body_header(name: &str) -> bool {
    name.eq_ignore_ascii_case(CONTENT_ENCODING_HEADER)
        || name.eq_ignore_ascii_case(CONTENT_LENGTH_HEADER)
}

#[cfg(test)]
mod tests {
    use super::{content_coding_plan, decoded_response_headers, ContentCoding, ContentCodingPlan};
    use super::{
        decode_body, decode_content_coding, decode_deflate, decode_reader,
        response_body_decoding_plan, CollectedBody,
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
}
