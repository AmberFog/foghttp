use super::super::test_control::{
    DecodeCheckpointEvent, DecodeCheckpointTarget, DecodeTestControl,
};
use crate::core::metrics::Metrics;
use crate::core::response::{response_body_decoding_plan, BufferedBodyBudget, CollectedBody};
use crate::py::client::transport::context::RawResponseContext;
use flate2::write::{DeflateEncoder, GzEncoder};
use flate2::Compression;
use hyper::header::CONTENT_ENCODING;
use hyper::HeaderMap;
use pyo3::prelude::*;
use std::io::Write;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::oneshot;
use tokio::task::JoinHandle;

pub(super) const WATCHDOG: Duration = Duration::from_secs(10);
pub(super) const BODY_SIZE: usize = 32 * 1024;
pub(super) static BODY: [u8; BODY_SIZE] = [b'x'; BODY_SIZE];

pub(super) fn gzip(content: &[u8]) -> Vec<u8> {
    let mut encoder = GzEncoder::new(Vec::new(), Compression::fast());
    encoder.write_all(content).unwrap();
    encoder.finish().unwrap()
}

pub(super) fn encoded_case(target: DecodeCheckpointTarget) -> (Vec<u8>, &'static str) {
    match target {
        DecodeCheckpointTarget::BetweenLayers { .. } => (gzip(&gzip(&BODY)), "gzip,gzip"),
        DecodeCheckpointTarget::RawDeflate => {
            let mut encoder = DeflateEncoder::new(Vec::new(), Compression::fast());
            encoder.write_all(&BODY).unwrap();
            (encoder.finish().unwrap(), "deflate")
        }
        _ => (gzip(&BODY), "gzip"),
    }
}

pub(super) struct ControlledDecode {
    pub control: Arc<DecodeTestControl>,
    pub reached: oneshot::Receiver<DecodeCheckpointEvent>,
    pub release: oneshot::Sender<()>,
    pub task: JoinHandle<PyResult<crate::core::response::ResponseBody>>,
    pub metrics: Arc<Metrics>,
    pub started: Instant,
}

pub(super) fn controlled_decode(target: DecodeCheckpointTarget) -> ControlledDecode {
    let (encoded, coding) = encoded_case(target);
    let metrics = Arc::new(Metrics::default());
    let budget = BufferedBodyBudget::new(Some(BODY_SIZE * 4), Arc::clone(&metrics));
    let mut reservation = budget.start_response();
    reservation.reserve_chunk(encoded.len()).unwrap();
    let collected = CollectedBody {
        content: encoded,
        reservation,
    };
    let mut headers = HeaderMap::new();
    headers.insert(CONTENT_ENCODING, coding.parse().unwrap());
    let plan = response_body_decoding_plan(&headers);
    let (control, reached, release) = DecodeTestControl::new(target);
    let control = Arc::new(control);
    let task_control = Arc::clone(&control);
    let started = Instant::now();
    let task = tokio::spawn(async move {
        let context = RawResponseContext {
            started,
            total_timeout: 1.0,
            read_timeout: 10.0,
            max_response_body_size: Some(BODY_SIZE),
            buffered_body_budget: budget,
            buffered_decoders: Arc::new(tokio::sync::Semaphore::new(1)),
            origin: "http://collected.example",
            redirect_hop: 3,
            decode_checkpoint: Some(&task_control),
        };
        super::super::decode_response_body(collected, plan, &context).await
    });
    ControlledDecode {
        control,
        reached,
        release,
        task,
        metrics,
        started,
    }
}

pub(super) async fn reach_checkpoint(
    reached: oneshot::Receiver<DecodeCheckpointEvent>,
) -> DecodeCheckpointEvent {
    tokio::time::timeout(WATCHDOG, reached)
        .await
        .expect("decoder did not reach selected post-EOF checkpoint")
        .expect("decoder task exited before selected checkpoint")
}
