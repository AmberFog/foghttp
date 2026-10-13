use super::*;
use flate2::Compression;
use hyper::header::HeaderValue;
use std::io::Write;

pub(super) fn plan(codings: &str) -> StreamingDecodePlan {
    let mut headers = HeaderMap::new();
    headers.insert(CONTENT_ENCODING, HeaderValue::from_str(codings).unwrap());
    StreamingDecodePlan::from_headers(&headers).unwrap()
}

pub(super) fn encode(coding: &str, input: &[u8]) -> Vec<u8> {
    match coding {
        "gzip" => {
            let mut writer = flate2::write::GzEncoder::new(Vec::new(), Compression::fast());
            writer.write_all(input).unwrap();
            writer.finish().unwrap()
        }
        "deflate" => {
            let mut writer = flate2::write::ZlibEncoder::new(Vec::new(), Compression::fast());
            writer.write_all(input).unwrap();
            writer.finish().unwrap()
        }
        "br" => {
            let mut writer = brotli::CompressorWriter::new(Vec::new(), 8192, 4, 22);
            writer.write_all(input).unwrap();
            writer.into_inner()
        }
        _ => input.to_vec(),
    }
}

fn decode(
    codings: &str,
    input: &[u8],
    split: usize,
    limit: Option<usize>,
) -> Result<Vec<u8>, StreamDecodeError> {
    let mut decoder = StreamingDecoder::new(plan(codings), limit);
    let mut output = Vec::new();
    let mut offset = 0;
    let mut end = split.min(input.len());
    let step_budget = input
        .len()
        .saturating_mul(4 * MAX_LAYERS)
        .saturating_add(100_000);
    for _ in 0..step_budget {
        let before = progress_snapshot(&decoder);
        let step = decoder.step(&input[offset..end], end == input.len())?;
        assert!(step.consumed <= INPUT_SIZE);
        assert!(step.consumed <= end - offset);
        offset += step.consumed;
        if step.status == StepStatus::Finished {
            assert!(step.output.is_none());
        }
        if let Some(chunk) = step.output {
            assert!(!chunk.is_empty() && chunk.len() <= OUTPUT_SIZE);
            output.extend_from_slice(&chunk);
        }
        match step.status {
            StepStatus::NeedsInput => {
                assert_eq!(
                    offset, end,
                    "requested input before consuming retained bytes"
                );
                assert!(end < input.len(), "requested input past EOF");
                end = (end + split).min(input.len());
            }
            StepStatus::Progress => assert_ne!(
                before,
                progress_snapshot(&decoder),
                "unchanged decoder reported progress"
            ),
            StepStatus::Finished => {
                assert_eq!(offset, input.len());
                return Ok(output);
            }
        }
    }
    panic!(
        "decoder failed to terminate: {codings}, split={split}, offset={offset}/{}",
        input.len()
    );
}

fn progress_snapshot(
    decoder: &StreamingDecoder,
) -> (usize, usize, bool, Vec<(usize, usize, LayerState)>) {
    (
        decoder.encoded_bytes,
        decoder.identity_bytes,
        decoder.finished,
        decoder
            .layers
            .iter()
            .map(|layer| (layer.produced, layer.input.len(), layer.state))
            .collect(),
    )
}

pub(super) fn first_output(
    decoder: &mut StreamingDecoder,
    input: &[u8],
) -> Result<Bytes, StreamDecodeError> {
    let mut consumed = 0;
    for _ in 0..100_000 {
        let step = decoder.step(&input[consumed..], true)?;
        consumed += step.consumed;
        if let Some(output) = step.output {
            return Ok(output);
        }
        assert_ne!(step.status, StepStatus::Finished, "expected nonempty body");
        assert_ne!(step.status, StepStatus::NeedsInput);
    }
    panic!("decoder did not reach first output");
}

#[test]
fn round_trips_at_arbitrary_boundaries_and_exact_limits() {
    let payload = b"streaming decoder test data ".repeat(2048);
    for coding in ["", "gzip", "deflate", "br"] {
        let encoded = encode(coding, &payload);
        for split in [1, 2, 7, 257, 8192, usize::MAX / 2] {
            assert_eq!(
                decode(coding, &encoded, split, Some(payload.len())).unwrap(),
                payload,
                "{coding}, {split}"
            );
        }
    }
}

#[test]
fn rejects_every_truncated_fixture_offset() {
    for coding in ["gzip", "deflate", "br"] {
        let encoded = encode(coding, &b"payload-".repeat(128));
        for offset in 0..encoded.len() {
            assert!(
                decode(coding, &encoded[..offset], 7, None).is_err(),
                "{coding} accepted prefix {offset}/{}",
                encoded.len()
            );
        }
    }
}

#[test]
fn empty_encoded_streams_and_gzip_members() {
    for coding in ["gzip", "deflate", "br"] {
        assert!(decode(coding, &encode(coding, b""), 1, Some(0))
            .unwrap()
            .is_empty());
    }
    let encoded = [
        encode("gzip", b""),
        encode("gzip", b"first"),
        encode("gzip", b""),
        encode("gzip", b"second"),
    ]
    .concat();
    assert_eq!(decode("gzip", &encoded, 1, None).unwrap(), b"firstsecond");
}

#[test]
fn plans_preserve_field_order_ignore_identity_and_reserve_exactly() {
    for coding in ["", "identity", " , \tIDENTITY, ,"] {
        let plan = plan(coding);
        assert!(!plan.is_encoded());
        assert_eq!(plan.reservation_bytes(), 2 * OUTPUT_SIZE);
    }
    let mut headers = HeaderMap::new();
    headers.append(
        CONTENT_ENCODING,
        HeaderValue::from_static(" GzIp, identity, "),
    );
    headers.append(
        CONTENT_ENCODING,
        HeaderValue::from_static("BR, X-GZIP\t, deFLAte"),
    );
    let plan = StreamingDecodePlan::from_headers(&headers).unwrap();
    assert!(plan.is_encoded());
    assert_eq!(
        plan.codings
            .iter()
            .copied()
            .map(Coding::name)
            .collect::<Vec<_>>(),
        ["deflate", "gzip", "br", "gzip"]
    );
    assert_eq!(
        plan.reservation_bytes(),
        3 * INFLATE_RESERVATION + BROTLI_RESERVATION + 6 * OUTPUT_SIZE
    );
    assert_eq!(
        self::plan("br,br,br,br").reservation_bytes(),
        4 * BROTLI_RESERVATION + 6 * OUTPUT_SIZE
    );
}

#[test]
fn invalid_plans_fail_before_decoder_construction_without_header_disclosure() {
    for (value, reason) in [
        ("gzip; q=1", "syntax"),
        ("gzip deflate", "syntax"),
        ("\"gzip\"", "syntax"),
        ("gzip, secret-unsupported-value", "unsupported"),
        ("gzip,gzip,gzip,gzip,gzip", "four layers"),
    ] {
        let mut headers = HeaderMap::new();
        headers.insert(CONTENT_ENCODING, HeaderValue::from_str(value).unwrap());
        let error = StreamingDecodePlan::from_headers(&headers).unwrap_err();
        assert!(error.to_string().contains(reason));
        assert!(!error.to_string().contains("secret-unsupported-value"));
    }
    let mut headers = HeaderMap::new();
    headers.insert(CONTENT_ENCODING, HeaderValue::from_bytes(b"\xff").unwrap());
    assert!(matches!(
        StreamingDecodePlan::from_headers(&headers),
        Err(StreamDecodeError::InvalidContentEncoding)
    ));
}

#[test]
fn nested_layers_decode_in_reverse_with_bounded_work() {
    let payload = b"four nested layers ".repeat(8192);
    for codings in [
        vec!["gzip", "br"],
        vec!["gzip", "deflate", "br", "gzip"],
        vec!["br"; 4],
        vec!["gzip"; 4],
    ] {
        let mut encoded = payload.clone();
        for coding in &codings {
            encoded = encode(coding, &encoded);
        }
        for split in [1, 7, 8192, encoded.len()] {
            assert_eq!(
                decode(&codings.join(","), &encoded, split, Some(payload.len())).unwrap(),
                payload
            );
        }
    }
}

#[test]
fn trailing_bytes_and_non_gzip_concatenation_are_rejected() {
    for coding in ["gzip", "deflate", "br"] {
        let encoded = encode(coding, b"valid prefix");
        for suffix in [b"\0".as_slice(), b"junk", b"\0\0\0\0"] {
            let input = [encoded.as_slice(), suffix].concat();
            for split in [1, encoded.len(), input.len()] {
                assert!(
                    matches!(
                        decode(coding, &input, split, None),
                        Err(StreamDecodeError::Decode { .. })
                    ),
                    "{coding}"
                );
            }
        }
        if coding != "gzip" {
            assert!(decode(coding, &encoded.repeat(2), encoded.len(), None).is_err());
        }
    }
}

#[test]
fn checksum_and_member_header_errors_are_terminal() {
    for coding in ["gzip", "deflate"] {
        let encoded = encode(coding, &b"checksum payload".repeat(8192));
        for corruption in if coding == "gzip" {
            vec![0, 3, encoded.len() - 8, encoded.len() - 1]
        } else {
            vec![0, encoded.len() - 1]
        } {
            let mut input = encoded.clone();
            input[corruption] ^= 0x80;
            let mut decoder = StreamingDecoder::new(plan(coding), None);
            let mut offset = 0;
            let error = loop {
                match decoder.step(&input[offset..], true) {
                    Ok(step) => {
                        assert_ne!(step.status, StepStatus::Finished);
                        offset += step.consumed;
                    }
                    Err(error) => break error,
                }
            };
            assert!(matches!(error, StreamDecodeError::Decode { .. }));
            assert_eq!(
                decoder.step(b"", true).unwrap_err().to_string(),
                error.to_string()
            );
            assert_eq!(
                decoder.step(&encoded, false).unwrap_err().to_string(),
                error.to_string()
            );
            assert!(std::error::Error::source(&error).is_some());
        }
    }
}

#[test]
fn strict_deflate_rejects_raw_and_preset_dictionary() {
    let mut writer = flate2::write::DeflateEncoder::new(Vec::new(), Compression::fast());
    writer.write_all(b"raw deflate is not zlib").unwrap();
    let raw = writer.finish().unwrap();
    assert!(decode("deflate", &raw, 1, None).is_err());
    assert!(decode("deflate", &[0x78, 0x20, 0, 0, 0, 1], 1, None).is_err());
}

#[test]
fn strict_brotli_rejects_large_window_extension() {
    let params = brotli::enc::BrotliEncoderParams {
        quality: 4,
        lgwin: 25,
        large_window: true,
        ..Default::default()
    };
    let mut encoded = Vec::new();
    brotli::BrotliCompress(
        &mut b"large window extension".as_slice(),
        &mut encoded,
        &params,
    )
    .unwrap();
    let mut permissive = brotli::Decompressor::new(encoded.as_slice(), 8192);
    let mut reference = Vec::new();
    std::io::Read::read_to_end(&mut permissive, &mut reference).unwrap();
    assert_eq!(reference, b"large window extension");
    assert!(decode("br", &encoded, 1, None).is_err());
}

#[test]
fn output_caps_cover_identity_and_every_intermediate_layer() {
    let payload = b"limited output".repeat(8192);
    for coding in ["", "gzip", "deflate", "br"] {
        let encoded = encode(coding, &payload);
        for limit in [0, 1, payload.len() - 1] {
            assert!(
                matches!(decode(coding, &encoded, 7, Some(limit)), Err(StreamDecodeError::TooLarge { limit: observed, .. }) if observed == limit)
            );
        }
        assert_eq!(decode(coding, &encoded, 7, None).unwrap(), payload);
    }
    let mut encoded = Vec::new();
    for _ in 0..4 {
        encoded = encode("gzip", &encoded);
    }
    // Final output is empty, but the first intermediate exceeds zero.
    assert!(matches!(
        decode("gzip,gzip,gzip,gzip", &encoded, 7, Some(0)),
        Err(StreamDecodeError::TooLarge { layer: 0, .. })
    ));
    // Highly compressible outer representation, then expanding inner layer.
    let inner = encode("gzip", &payload);
    let outer = encode("br", &inner);
    assert!(matches!(
        decode("gzip,br", &outer, 7, Some(inner.len())),
        Err(StreamDecodeError::TooLarge { layer: 1, .. })
    ));
}

#[test]
fn byte_counters_fail_closed_on_overflow() {
    assert!(matches!(
        checked_output(usize::MAX, 1, None, "gzip", 0),
        Err(StreamDecodeError::CounterOverflow)
    ));
    let mut decoder = StreamingDecoder::new(plan(""), None);
    decoder.encoded_bytes = usize::MAX;
    assert!(matches!(
        decoder.step(b"x", false),
        Err(StreamDecodeError::CounterOverflow)
    ));
    let mut decoder = StreamingDecoder::new(plan("gzip"), None);
    decoder.layers[0].produced = usize::MAX;
    assert!(matches!(
        first_output(&mut decoder, &encode("gzip", b"x")),
        Err(StreamDecodeError::CounterOverflow)
    ));
}

#[test]
fn starvation_is_not_eof_and_final_output_precedes_completion() {
    for coding in ["", "gzip", "deflate", "br"] {
        let encoded = encode(coding, &vec![0x5a; 2 * OUTPUT_SIZE]);
        let mut decoder = StreamingDecoder::new(plan(coding), None);
        for _ in 0..3 {
            assert_eq!(
                decoder.step(b"", false).unwrap().status,
                StepStatus::NeedsInput
            );
        }
        let mut consumed = 0;
        let mut delivered = 0;
        for _ in 0..10_000 {
            let step = decoder.step(&encoded[consumed..], false).unwrap();
            consumed += step.consumed;
            assert_ne!(step.status, StepStatus::Finished);
            delivered += step.output.map_or(0, |chunk| chunk.len());
            if step.status == StepStatus::NeedsInput {
                assert_eq!(consumed, encoded.len());
                break;
            }
        }
        for _ in 0..100 {
            let step = decoder.step(b"", true).unwrap();
            assert_ne!(step.status, StepStatus::NeedsInput);
            if step.status == StepStatus::Finished {
                assert!(step.output.is_none());
                break;
            }
            delivered += step.output.map_or(0, |chunk| chunk.len());
        }
        assert_eq!(delivered, 2 * OUTPUT_SIZE);
        assert_eq!(
            decoder.step(b"", true).unwrap().status,
            StepStatus::Finished
        );
    }
}

#[test]
fn gzip_starvation_waits_when_inflate_really_needs_input() {
    assert_gzip_starvation_output(167, 0);
}

#[test]
fn gzip_starvation_drains_available_output_before_requesting_input() {
    assert_gzip_starvation_output(168, 258);
}

fn assert_gzip_starvation_output(prefix: usize, pending_output: usize) {
    let payload = vec![0x5a; 2 * OUTPUT_SIZE];
    let encoded = encode("gzip", &payload);
    // GzEncoder's default header has no optional fields; exclude its trailer.
    assert_eq!(&encoded[..4], &[0x1f, 0x8b, 8, 0]);
    let body = &encoded[10..encoded.len() - 8];
    let mut scratch = vec![0; OUTPUT_SIZE];
    let mut raw = flate2::Decompress::new(false);
    raw.decompress(&body[..prefix], &mut scratch, flate2::FlushDecompress::None)
        .unwrap();
    assert_eq!(usize::try_from(raw.total_in()).unwrap(), prefix);
    let initial_output = usize::try_from(raw.total_out()).unwrap();
    let mut expected = scratch[..initial_output].to_vec();
    // No new compressed bytes and no Finish: extra output is not input hunger.
    raw.decompress(&[], &mut scratch, flate2::FlushDecompress::None)
        .unwrap();
    assert_eq!(usize::try_from(raw.total_in()).unwrap(), prefix);
    assert_eq!(
        usize::try_from(raw.total_out()).unwrap() - initial_output,
        pending_output
    );
    expected.extend_from_slice(&scratch[..pending_output]);
    assert!(expected.iter().all(|byte| *byte == 0x5a));
    raw.decompress(&[], &mut scratch, flate2::FlushDecompress::None)
        .unwrap();
    assert_eq!(usize::try_from(raw.total_out()).unwrap(), expected.len());

    let mut decoder = StreamingDecoder::new(plan("gzip"), None);
    let mut consumed = 0;
    let mut actual = Vec::new();
    let mut needs_input = false;
    for _ in 0..100 {
        let step = decoder
            .step(&encoded[consumed..10 + prefix], false)
            .unwrap();
        consumed += step.consumed;
        assert_ne!(step.status, StepStatus::Finished);
        if let Some(output) = step.output {
            actual.extend_from_slice(&output);
        }
        if step.status == StepStatus::NeedsInput {
            needs_input = true;
            break;
        }
    }
    assert!(needs_input, "decoder never reached input starvation");
    assert_eq!(consumed, 10 + prefix);
    eprintln!(
        "gzip prefix {}: delivered {}, raw inflate {initial_output} + {pending_output} without input",
        10 + prefix,
        actual.len()
    );
    assert_eq!(actual.len(), expected.len(), "deflate prefix {prefix}");
    assert_eq!(actual, expected, "deflate prefix {prefix}");
}

fn brotli_flushed_prefix(payload: &[u8]) -> (Vec<u8>, usize) {
    let mut writer = brotli::CompressorWriter::new(Vec::new(), 8192, 4, 22);
    writer.write_all(payload).unwrap();
    writer.flush().unwrap();
    let prefix = writer.get_ref().len();
    let encoded = writer.into_inner();
    assert!(prefix < encoded.len());
    assert!(prefix <= INPUT_SIZE);
    (encoded, prefix)
}

#[test]
fn brotli_starvation_drains_incomplete_prefix_before_requesting_input() {
    let payload = vec![0x5a; 3 * OUTPUT_SIZE + 17];
    let (encoded, prefix) = brotli_flushed_prefix(&payload);

    let mut raw = brotli::BrotliState::new_strict(
        brotli::HeapAlloc::default(),
        brotli::HeapAlloc::default(),
        brotli::HeapAlloc::default(),
    );
    let mut scratch = vec![0; OUTPUT_SIZE];
    let mut expected = Vec::new();
    let mut raw_consumed = 0;
    let mut raw_produced = Vec::new();
    for _ in 0..6 {
        let input = &encoded[raw_consumed..prefix];
        let mut available_in = input.len();
        let mut consumed = 0;
        let mut available_out = scratch.len();
        let mut produced = 0;
        let mut total_out = 0;
        let result = brotli::BrotliDecompressStream(
            &mut available_in,
            &mut consumed,
            input,
            &mut available_out,
            &mut produced,
            &mut scratch,
            &mut total_out,
            &mut raw,
        );
        assert!(matches!(result, brotli::BrotliResult::NeedsMoreInput));
        raw_consumed += consumed;
        assert_eq!(raw_consumed, prefix);
        expected.extend_from_slice(&scratch[..produced]);
        raw_produced.push(produced);
        if produced == 0 {
            break;
        }
    }
    assert_eq!(raw_produced, [OUTPUT_SIZE, OUTPUT_SIZE, OUTPUT_SIZE, 17, 0]);
    assert_eq!(expected, payload);

    let mut decoder = StreamingDecoder::new(plan("br"), None);
    let first = decoder.step(&encoded[..prefix], false).unwrap();
    assert_eq!(first.consumed, prefix);
    assert_eq!(first.status, StepStatus::Progress);
    let mut actual = first.output.unwrap().to_vec();
    let mut needs_input = false;
    for _ in 0..6 {
        let before = progress_snapshot(&decoder);
        let step = decoder.step(b"", false).unwrap();
        assert_eq!(step.consumed, 0);
        assert_ne!(step.status, StepStatus::Finished);
        if let Some(output) = step.output {
            assert!(output.len() <= OUTPUT_SIZE);
            actual.extend_from_slice(&output);
        }
        if step.status == StepStatus::NeedsInput {
            needs_input = true;
            break;
        }
        assert_ne!(before, progress_snapshot(&decoder));
    }
    assert!(needs_input, "decoder never reached input starvation");
    eprintln!(
        "Brotli prefix {prefix}/{}: raw output {raw_produced:?}, driver delivered {}",
        encoded.len(),
        actual.len()
    );
    assert_eq!(actual.len(), expected.len());
    assert_eq!(actual, expected);
    assert_eq!(decoder.encoded_bytes, prefix);

    let starved = progress_snapshot(&decoder);
    for _ in 0..3 {
        let step = decoder.step(b"", false).unwrap();
        assert_eq!(step.status, StepStatus::NeedsInput);
        assert_eq!(step.consumed, 0);
        assert!(step.output.is_none());
        assert_eq!(progress_snapshot(&decoder), starved);
    }
    let last = decoder.step(&encoded[prefix..], true).unwrap();
    assert_eq!(last.status, StepStatus::Progress);
    assert_eq!(last.consumed, encoded.len() - prefix);
    assert!(last.output.is_none());
    let finished = decoder.step(b"", true).unwrap();
    assert_eq!(finished.status, StepStatus::Finished);
    assert!(finished.output.is_none());
    assert_eq!(decoder.encoded_bytes, encoded.len());
}

#[test]
fn brotli_incomplete_prefix_eof_remains_a_terminal_error() {
    let (encoded, prefix) = brotli_flushed_prefix(&vec![0x5a; 3 * OUTPUT_SIZE + 17]);
    for drain_steps in 0..=5 {
        let mut decoder = StreamingDecoder::new(plan("br"), None);
        let mut consumed = 0;
        for _ in 0..drain_steps {
            let step = decoder.step(&encoded[consumed..prefix], false).unwrap();
            consumed += step.consumed;
            assert_ne!(step.status, StepStatus::Finished);
        }
        let error = decoder.step(&encoded[consumed..prefix], true).unwrap_err();
        match &error {
            StreamDecodeError::Decode {
                coding,
                layer,
                source,
            } => {
                assert_eq!(*coding, "br");
                assert_eq!(*layer, 0);
                assert_eq!(source.kind(), std::io::ErrorKind::UnexpectedEof);
            }
            other => panic!("expected Brotli truncation, got {other:?}"),
        }
        assert_eq!(
            decoder
                .step(&encoded[consumed..], false)
                .unwrap_err()
                .to_string(),
            error.to_string()
        );
    }
}

#[test]
fn brotli_incomplete_prefix_enforces_caps_during_empty_input_drain() {
    let payload = vec![0x5a; 3 * OUTPUT_SIZE + 17];
    let (encoded, prefix) = brotli_flushed_prefix(&payload);
    for limit in [
        0,
        OUTPUT_SIZE - 1,
        OUTPUT_SIZE,
        OUTPUT_SIZE + 1,
        payload.len() - 1,
    ] {
        let mut decoder = StreamingDecoder::new(plan("br"), Some(limit));
        let mut consumed = 0;
        let mut delivered = 0;
        let mut failed = false;
        for _ in 0..6 {
            match decoder.step(&encoded[consumed..prefix], false) {
                Ok(step) => {
                    consumed += step.consumed;
                    assert_eq!(step.status, StepStatus::Progress);
                    delivered += step.output.map_or(0, |output| output.len());
                    assert!(delivered <= limit);
                }
                Err(error) => {
                    assert!(matches!(
                        error,
                        StreamDecodeError::TooLarge { coding: "br", layer: 0, limit: observed }
                            if observed == limit
                    ));
                    assert_eq!(
                        decoder.step(b"", false).unwrap_err().to_string(),
                        error.to_string()
                    );
                    failed = true;
                    break;
                }
            }
        }
        assert!(
            failed,
            "limit {limit} was not checked before requesting input"
        );
        if limit >= OUTPUT_SIZE {
            assert_eq!(consumed, prefix);
            assert!(delivered >= OUTPUT_SIZE);
        }
    }
    assert_eq!(
        decode("br", &encoded, prefix, Some(payload.len())).unwrap(),
        payload
    );
}

#[test]
fn gzip_header_crc_and_long_optional_fields_are_library_validated() {
    let mut writer = flate2::GzBuilder::new()
        .filename(vec![b'n'; 65535])
        .comment(vec![b'c'; 65535])
        .extra(vec![9; 65535])
        .write(Vec::new(), Compression::fast());
    writer.write_all(b"header fields").unwrap();
    let encoded = writer.finish().unwrap();
    assert_eq!(
        decode("gzip", &encoded, 8192, None).unwrap(),
        b"header fields"
    );
    let too_long = flate2::GzBuilder::new()
        .filename(vec![b'n'; 65536])
        .write(Vec::new(), Compression::fast())
        .finish()
        .unwrap();
    assert!(decode("gzip", &too_long, 8192, None).is_err());

    let mut member = encode("gzip", b"header crc");
    member[3] |= 2;
    let mut checksum = flate2::Crc::new();
    checksum.update(&member[..10]);
    let header_crc = checksum.sum().to_le_bytes();
    member.splice(10..10, header_crc[..2].iter().copied());
    assert_eq!(decode("gzip", &member, 1, None).unwrap(), b"header crc");
    member[10] ^= 1;
    assert!(decode("gzip", &member, 1, None).is_err());
}

#[test]
fn input_is_retained_while_downstream_drains_and_errors_never_expose_excess() {
    let payload = vec![51; 8 * OUTPUT_SIZE];
    let input = encode("br", &encode("gzip", &payload));
    let limit = 2 * OUTPUT_SIZE;
    let mut decoder = StreamingDecoder::new(plan("gzip,br"), Some(limit));
    let mut consumed = 0;
    let mut delivered = 0;
    let mut saw_error = false;
    for _ in 0..1000 {
        match decoder.step(&input[consumed..], true) {
            Ok(step) => {
                consumed += step.consumed;
                assert_eq!(step.status, StepStatus::Progress);
                delivered += step.output.map_or(0, |output| output.len());
                assert!(delivered <= limit);
            }
            Err(error) => {
                assert!(matches!(
                    error,
                    StreamDecodeError::TooLarge { layer: 1, .. }
                ));
                saw_error = true;
                break;
            }
        }
    }
    assert!(saw_error);
    assert!(delivered > 0);
}
