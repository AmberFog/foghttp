use super::state::{StreamState, StreamStateInner};
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard, Weak};

#[derive(Clone, Default)]
pub(crate) struct StreamRegistry {
    active: Arc<Mutex<HashMap<u64, Weak<StreamStateInner>>>>,
    next_stream_id: Arc<AtomicU64>,
}

impl StreamRegistry {
    pub(crate) fn abort_all(&self) {
        let active_streams = {
            let mut active = self.active_streams();
            let streams = active
                .values()
                .filter_map(Weak::upgrade)
                .map(|inner| StreamState { inner })
                .collect::<Vec<_>>();
            active.clear();
            streams
        };

        for stream in active_streams {
            stream.abort();
        }
    }

    pub(super) fn insert(&self, stream_id: u64, stream: &Arc<StreamStateInner>) {
        self.active_streams()
            .insert(stream_id, Arc::downgrade(stream));
    }

    pub(super) fn next_stream_id(&self) -> u64 {
        self.next_stream_id.fetch_add(1, Ordering::Relaxed)
    }

    pub(super) fn remove(&self, stream_id: u64) {
        self.active_streams().remove(&stream_id);
    }

    fn active_streams(&self) -> MutexGuard<'_, HashMap<u64, Weak<StreamStateInner>>> {
        self.active
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}
