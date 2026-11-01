use crate::core::response::{BufferedDecodeProgress, BufferedDecodeStatus};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;
use tokio::sync::oneshot;

#[derive(Clone, Copy, Debug)]
pub(in crate::py::client::transport) enum DecodeCheckpointTarget {
    Output { layer: usize, minimum: usize },
    BetweenLayers { remaining: usize },
    RawDeflate,
    Finished,
    NativeReturn,
}

#[derive(Clone, Copy, Debug)]
pub(in crate::py::client::transport) struct DecodeCheckpointEvent {
    pub progress: BufferedDecodeProgress,
    pub status: BufferedDecodeStatus,
}

pub(in crate::py::client::transport) struct DecodeTestControl {
    target: DecodeCheckpointTarget,
    visits: AtomicUsize,
    final_step: Mutex<Option<DecodeCheckpointEvent>>,
    reached: Mutex<Option<oneshot::Sender<DecodeCheckpointEvent>>>,
    release: Mutex<Option<oneshot::Receiver<()>>>,
}

impl DecodeTestControl {
    pub(in crate::py::client::transport) fn new(
        target: DecodeCheckpointTarget,
    ) -> (
        Self,
        oneshot::Receiver<DecodeCheckpointEvent>,
        oneshot::Sender<()>,
    ) {
        let (reached, observed) = oneshot::channel();
        let (resume, release) = oneshot::channel();
        (
            Self {
                target,
                visits: AtomicUsize::new(0),
                final_step: Mutex::new(None),
                reached: Mutex::new(Some(reached)),
                release: Mutex::new(Some(release)),
            },
            observed,
            resume,
        )
    }

    pub(in crate::py::client::transport) fn visits(&self) -> usize {
        self.visits.load(Ordering::SeqCst)
    }

    pub(super) async fn after_step(
        &self,
        progress: BufferedDecodeProgress,
        status: BufferedDecodeStatus,
    ) {
        self.visits.fetch_add(1, Ordering::SeqCst);
        let event = DecodeCheckpointEvent { progress, status };
        if matches!(self.target, DecodeCheckpointTarget::NativeReturn)
            && status == BufferedDecodeStatus::Finished
        {
            *self.final_step.lock().expect("test checkpoint lock") = Some(event);
        }
        let selected = match self.target {
            DecodeCheckpointTarget::Output { layer, minimum } => {
                progress.completed_layers == layer && progress.output_bytes >= minimum
            }
            DecodeCheckpointTarget::BetweenLayers { remaining } => {
                progress.completed_layers > 0
                    && progress.remaining_layers == remaining
                    && progress.output_bytes == 0
            }
            DecodeCheckpointTarget::RawDeflate => {
                progress.raw_deflate && progress.output_bytes == 0
            }
            DecodeCheckpointTarget::Finished => status == BufferedDecodeStatus::Finished,
            DecodeCheckpointTarget::NativeReturn => false,
        };
        if !selected {
            return;
        }
        self.wait_selected(event).await;
    }

    pub(in crate::py::client::transport) async fn before_return(&self) {
        if !matches!(self.target, DecodeCheckpointTarget::NativeReturn) {
            return;
        }
        let event = self
            .final_step
            .lock()
            .expect("test checkpoint lock")
            .take()
            .expect("native return follows a completed codec step");
        self.wait_selected(event).await;
    }

    async fn wait_selected(&self, event: DecodeCheckpointEvent) {
        let Some(reached) = self.reached.lock().expect("test checkpoint lock").take() else {
            return;
        };
        let release = self
            .release
            .lock()
            .expect("test checkpoint lock")
            .take()
            .expect("selected checkpoint owns its release receiver");
        reached
            .send(event)
            .expect("test observes selected checkpoint");
        release.await.expect("test releases selected checkpoint");
    }
}
