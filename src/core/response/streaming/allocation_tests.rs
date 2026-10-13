//! Allocation evidence for the exact codec builds qualified by TASK-123.
//!
//! flate2 1.1.9 `gz/mod.rs` bounds extra/name/comment at 65535 bytes each;
//! name/comment `Vec` capacities are at most 65536. `ffi/miniz_oxide.rs` owns
//! one boxed `miniz_oxide` 0.8.9 `InflateState` (fixed tables and 32768-byte window).
//! gzip replaces, rather than accumulates, member headers.
//!
//! brotli-decompressor 5.0.3 `decode.rs` allocates the ring only while absent;
//! `new_strict` limits its size to 2^24 + 42 + 24 bytes. Three Huffman groups
//! have at most 256 * 1080 four-byte entries and 256 u32 offsets apiece.
//! Seven auxiliary tables have 1080 entries each, context maps have at most
//! 256 * (64 + 4) bytes, and context modes at most 256 bytes. Metablock begin
//! frees the preceding groups/maps. `HeapAlloc` uses exactly sized boxed slices.
//! These bounds leave over 12 MiB of the 32 MiB ceiling for fixed state,
//! stack tables and transient allocation overlap. They require requalification
//! if the pinned dependencies or their selected features change.
//!
//! Pipeline live buffers: one 64 KiB scratch, at most (layers - 1) 64 KiB
//! inter-layer slots, and one new 64 KiB output allocation. Replacing an empty
//! slot may retain its old allocation until assignment; that old slot is already
//! counted. The reservation's (layers + 2) slots also cover control structures
//! and identity delivery. The gzip write adapter owns a fixed 64 KiB sink;
//! flate2's `zio::Writer` has a fixed-capacity 32 KiB output Vec. Both fit inside
//! the 1 MiB gzip ceiling, including overlap when replacing a member decoder.

#![allow(unsafe_code)]

use super::tests::{encode, first_output, plan};
use super::{StepStatus, StreamingDecoder, OUTPUT_SIZE};
use brotli::{
    Allocator, BrotliDecompressStream, BrotliResult, BrotliState, HeapAlloc, HuffmanCode,
};
use flate2::bufread::MultiGzDecoder;
use flate2::{Compression, Decompress, FlushDecompress, GzBuilder, Status};
use std::alloc::{GlobalAlloc, Layout, System};
use std::cell::Cell;
use std::io::{BufReader, Cursor, Read, Write};

struct MeasuringAllocator;

#[derive(Clone, Copy, Default)]
struct AllocationCount {
    enabled: bool,
    invalid: bool,
    live: usize,
    peak: usize,
}

thread_local! {
    static ALLOCATIONS: Cell<AllocationCount> = const { Cell::new(AllocationCount {
        enabled: false, invalid: false, live: 0, peak: 0,
    }) };
}

fn allocated(bytes: usize) {
    let _ = ALLOCATIONS.try_with(|cell| {
        let mut count = cell.get();
        if count.enabled && !count.invalid {
            if let Some(live) = count.live.checked_add(bytes) {
                count.live = live;
                count.peak = count.peak.max(live);
            } else {
                count.invalid = true;
            }
            cell.set(count);
        }
    });
}

fn freed(bytes: usize) {
    let _ = ALLOCATIONS.try_with(|cell| {
        let mut count = cell.get();
        if count.enabled && !count.invalid {
            if let Some(live) = count.live.checked_sub(bytes) {
                count.live = live;
            } else {
                count.invalid = true;
            }
            cell.set(count);
        }
    });
}

// SAFETY: Every operation forwards the original pointer/layout to System.
// The const-initialized thread-local accounting neither allocates nor panics;
// arithmetic failures are reported only after measurement is disabled.
unsafe impl GlobalAlloc for MeasuringAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        // SAFETY: System receives the original valid allocation layout.
        let pointer = unsafe { System.alloc(layout) };
        if !pointer.is_null() {
            allocated(layout.size());
        }
        pointer
    }

    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        // SAFETY: System receives the original valid allocation layout.
        let pointer = unsafe { System.alloc_zeroed(layout) };
        if !pointer.is_null() {
            allocated(layout.size());
        }
        pointer
    }

    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        freed(layout.size());
        // SAFETY: The original System pointer and its layout are unchanged.
        unsafe { System.dealloc(pointer, layout) };
    }

    unsafe fn realloc(&self, pointer: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        // SAFETY: Forward the caller's valid pointer, layout and new size.
        let result = unsafe { System.realloc(pointer, layout, size) };
        if !result.is_null() {
            // Count old/new overlap even when the allocator grew in place.
            allocated(size);
            freed(layout.size());
        }
        result
    }
}

#[global_allocator]
static ALLOCATOR: MeasuringAllocator = MeasuringAllocator;

pub(super) fn measure(work: impl FnOnce()) -> usize {
    struct Reset;
    impl Drop for Reset {
        fn drop(&mut self) {
            ALLOCATIONS.with(|cell| cell.set(AllocationCount::default()));
        }
    }
    let reset = Reset;
    ALLOCATIONS.with(|cell| {
        assert!(!cell.get().enabled);
        cell.set(AllocationCount {
            enabled: true,
            ..AllocationCount::default()
        });
    });
    work();
    let result = ALLOCATIONS.with(Cell::get);
    drop(reset);
    assert!(!result.invalid, "allocation measurement accounting invalid");
    assert_eq!(result.live, 0, "decoder-owned allocation leaked");
    result.peak
}

#[test]
fn allocation_measurement_rejects_foreign_deallocation_after_disabling() {
    let foreign = vec![0u8; 1024];
    let mut invalid_during_work = false;
    let failure = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        measure(|| {
            drop(std::hint::black_box(foreign));
            invalid_during_work = ALLOCATIONS.with(|cell| {
                let count = cell.get();
                count.enabled && count.invalid
            });
        });
    }));
    assert!(!ALLOCATIONS.with(|cell| cell.get().enabled));
    assert!(invalid_during_work);
    let error = failure.expect_err("foreign deallocation must invalidate measurement");
    assert_eq!(
        error.downcast_ref::<&str>(),
        Some(&"allocation measurement accounting invalid")
    );
    assert_eq!(measure(|| {}), 0);
}

#[test]
fn allocation_measurement_rejects_overflow_after_disabling() {
    let mut invalid_during_work = false;
    let failure = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        measure(|| {
            allocated(usize::MAX);
            allocated(1);
            freed(usize::MAX);
            invalid_during_work = ALLOCATIONS.with(|cell| {
                let count = cell.get();
                count.enabled && count.invalid
            });
        });
    }));
    assert!(!ALLOCATIONS.with(|cell| cell.get().enabled));
    assert!(invalid_during_work);
    let error = failure.expect_err("overflow must invalidate measurement");
    assert_eq!(
        error.downcast_ref::<&str>(),
        Some(&"allocation measurement accounting invalid")
    );
    assert_eq!(measure(|| {}), 0);
}

#[test]
fn allocation_measurement_preserves_exact_peak_and_reallocation_overlap() {
    assert_eq!(
        measure(|| {
            allocated(10);
            allocated(20);
            freed(10);
            freed(20);
        }),
        30
    );
    assert_eq!(
        measure(|| {
            allocated(usize::MAX);
            freed(usize::MAX);
        }),
        usize::MAX
    );
}

#[test]
fn dependency_versions_require_allocation_requalification() {
    let manifest = include_str!(concat!(env!("CARGO_MANIFEST_DIR"), "/Cargo.toml"));
    assert!(manifest.contains("\nflate2 = \"1.1.9\"\n"));
    assert!(manifest.contains("\nbrotli = \"8.0.4\"\n"));
    let lock = include_str!(concat!(env!("CARGO_MANIFEST_DIR"), "/Cargo.lock"));
    for (name, version) in [
        ("flate2", "1.1.9"),
        ("miniz_oxide", "0.8.9"),
        ("brotli", "8.0.4"),
        ("brotli-decompressor", "5.0.3"),
        ("alloc-stdlib", "0.2.4"),
    ] {
        assert!(
            lock.contains(&format!("name = \"{name}\"\nversion = \"{version}\"")),
            "requalify the codec allocation proof for {name}"
        );
    }
}

#[test]
fn gzip_maximum_member_headers_fit_one_mib() {
    let mut encoder = GzBuilder::new()
        .extra(vec![1; 65535])
        .filename(vec![b'f'; 65535])
        .comment(vec![b'c'; 65535])
        .write(Vec::new(), Compression::fast());
    encoder.write_all(&vec![42; 32768]).unwrap();
    let member = encoder.finish().unwrap();
    let input = member.repeat(3);
    let mut output = vec![0; 65536];
    let peak = measure(|| {
        let reader = BufReader::with_capacity(8192, Cursor::new(&input));
        let mut decoder = MultiGzDecoder::new(reader);
        let mut total = 0;
        loop {
            let produced = decoder.read(&mut output).unwrap();
            if produced == 0 {
                break;
            }
            total += produced;
        }
        assert_eq!(total, 3 * 32768);
    });
    eprintln!("gzip maximum fields / 3 members: peak {peak} bytes");
    assert!(peak + 65536 < 1024 * 1024);
    let pipeline_peak = measure_pipeline("gzip", &input, 3 * 32768);
    assert!(pipeline_peak < 1024 * 1024);
}

#[test]
fn zlib_fixed_inflate_state_fits_one_mib() {
    let mut encoder = flate2::write::ZlibEncoder::new(Vec::new(), Compression::fast());
    encoder.write_all(&vec![17; 2 * 1024 * 1024]).unwrap();
    let input = encoder.finish().unwrap();
    let mut output = vec![0; 65536];
    let peak = measure(|| {
        let mut decoder = Decompress::new(true);
        loop {
            let start = usize::try_from(decoder.total_in()).unwrap();
            let end = (start + 8192).min(input.len());
            let status = decoder
                .decompress(&input[start..end], &mut output, FlushDecompress::None)
                .unwrap();
            if status == Status::StreamEnd {
                break;
            }
        }
        assert_eq!(decoder.total_out(), 2 * 1024 * 1024);
    });
    eprintln!("zlib fixed state: peak {peak} bytes");
    assert!(peak + 65536 < 1024 * 1024);
}

#[test]
fn brotli_maximum_standard_window_fits_32_mib() {
    let mut encoder = brotli::CompressorWriter::new(Vec::new(), 8192, 1, 24);
    let block = vec![29; 1024 * 1024];
    for _ in 0..17 {
        encoder.write_all(&block).unwrap();
    }
    let input = encoder.into_inner();
    let mut output = vec![0; 65536];
    let peak = measure(|| {
        let mut state = BrotliState::new_strict(
            HeapAlloc::default(),
            HeapAlloc::default(),
            HeapAlloc::default(),
        );
        let mut consumed = 0;
        let mut total_out = 0;
        loop {
            let end = (consumed + 8192).min(input.len());
            let chunk = &input[consumed..end];
            let mut available_in = chunk.len();
            let mut input_offset = 0;
            let mut available_out = output.len();
            let mut output_offset = 0;
            let result = BrotliDecompressStream(
                &mut available_in,
                &mut input_offset,
                chunk,
                &mut available_out,
                &mut output_offset,
                &mut output,
                &mut total_out,
                &mut state,
            );
            consumed += input_offset;
            match result {
                BrotliResult::ResultSuccess => break,
                BrotliResult::ResultFailure => panic!("valid standard Brotli rejected"),
                BrotliResult::NeedsMoreInput => assert!(consumed < input.len()),
                BrotliResult::NeedsMoreOutput => {}
            }
        }
        assert_eq!(state.window_bits, 24);
        assert_eq!(state.ringbuffer_size, 1 << 24);
        assert_eq!(total_out, 17 * 1024 * 1024);
    });
    eprintln!("brotli standard window 24: peak {peak} bytes");
    assert!(peak > 16 * 1024 * 1024);
    assert!(peak + 65536 < 32 * 1024 * 1024);
}

#[test]
fn brotli_all_maximum_tables_and_ring_allocation_envelope() {
    // This is the source-derived allocation envelope, not a bitstream fixture.
    // Exercise library allocation sites at their proven maxima simultaneously.
    let peak = measure(|| {
        let mut state = BrotliState::new_strict(
            HeapAlloc::<u8>::default(),
            HeapAlloc::<u32>::default(),
            HeapAlloc::<HuffmanCode>::default(),
        );
        state.ringbuffer = state.alloc_u8.alloc_cell((1 << 24) + 66);
        state.block_type_length_state.block_type_trees = state.alloc_hc.alloc_cell(3 * 1080);
        state.block_type_length_state.block_len_trees = state.alloc_hc.alloc_cell(3 * 1080);
        state.context_modes = state.alloc_u8.alloc_cell(256);
        state.context_map = state.alloc_u8.alloc_cell(256 * 64);
        state.dist_context_map = state.alloc_u8.alloc_cell(256 * 4);
        for _ in 0..3 {
            state
                .literal_hgroup
                .init(&mut state.alloc_u32, &mut state.alloc_hc, 256, 256, 256);
            state
                .insert_copy_hgroup
                .init(&mut state.alloc_u32, &mut state.alloc_hc, 704, 704, 256);
            state
                .distance_hgroup
                .init(&mut state.alloc_u32, &mut state.alloc_hc, 520, 520, 256);
        }
    });
    eprintln!("brotli maximum ring/tables envelope: peak {peak} bytes");
    assert_eq!(
        peak,
        (1 << 24) + 66 + 3 * 256 * (1080 * 4 + 4) + 7 * 1080 * 4 + 256 * (64 + 4 + 1)
    );
    assert!(peak > 19 * 1024 * 1024);
    assert!(peak + 65536 < 32 * 1024 * 1024);
}

fn measure_pipeline(codings: &str, input: &[u8], expected_size: usize) -> usize {
    let reservation = plan(codings).reservation_bytes();
    let peak = measure(|| {
        let mut decoder = StreamingDecoder::new(plan(codings), None);
        let mut consumed = 0;
        let mut produced = 0;
        let mut finished = false;
        for _ in 0..input.len().saturating_mul(16).saturating_add(10_000) {
            let step = decoder.step(&input[consumed..], true).unwrap();
            consumed += step.consumed;
            assert!(step.consumed <= super::INPUT_SIZE);
            assert!(decoder
                .layers
                .iter()
                .all(|layer| layer.input.len() <= OUTPUT_SIZE));
            if let Some(output) = step.output {
                assert!(output.len() <= OUTPUT_SIZE);
                produced += output.len();
            }
            assert_ne!(step.status, StepStatus::NeedsInput);
            if step.status == StepStatus::Finished {
                finished = true;
                break;
            }
        }
        assert!(finished);
        assert_eq!(consumed, input.len());
        assert_eq!(produced, expected_size);
    });
    eprintln!("pipeline {codings:?}: peak {peak} bytes / reservation {reservation}");
    assert!(peak <= reservation);
    peak
}

#[test]
fn pipeline_allocations_fit_identity_and_nested_inflate_reservations() {
    let mut payload = vec![0; 256 * 1024];
    fastrand::Rng::with_seed(123).fill(&mut payload);
    for codings in [
        "",
        "gzip",
        "deflate",
        "gzip,gzip,gzip,gzip",
        "gzip,br,deflate,gzip",
    ] {
        let mut input = payload.clone();
        for coding in codings.split(',') {
            input = encode(coding, &input);
        }
        measure_pipeline(codings, &input, payload.len());
    }
}

#[test]
fn four_maximum_brotli_windows_fit_pipeline_reservation() {
    let mut payload = vec![0; 256 * 1024];
    fastrand::Rng::with_seed(456).fill(&mut payload);
    let mut input = payload.clone();
    for _ in 0..4 {
        let mut encoder = brotli::CompressorWriter::new(Vec::new(), 8192, 1, 24);
        encoder.write_all(&input).unwrap();
        // A non-final block prevents the library's last-block ring downsizing.
        encoder.flush().unwrap();
        input = encoder.into_inner();
    }
    let peak = measure_pipeline("br,br,br,br", &input, payload.len());
    assert!(peak > 4 * (1 << 24));
}

#[test]
fn pipeline_allocations_release_after_failure_and_early_drop() {
    let payload = vec![42; 256 * 1024];
    for coding in ["gzip", "deflate", "br"] {
        let input = encode(coding, &payload);
        let peak = measure(|| {
            let mut decoder = StreamingDecoder::new(plan(coding), Some(1));
            let error = first_output(&mut decoder, &input).unwrap_err();
            assert!(matches!(error, super::StreamDecodeError::TooLarge { .. }));
            assert!(decoder.step(b"", true).is_err());
        });
        assert!(peak < plan(coding).reservation_bytes());
        let peak = measure(|| {
            let mut decoder = StreamingDecoder::new(plan(coding), None);
            let output = first_output(&mut decoder, &input).unwrap();
            assert!(!output.is_empty());
            assert!(!decoder.finished);
        });
        assert!(peak < plan(coding).reservation_bytes());
    }
}
