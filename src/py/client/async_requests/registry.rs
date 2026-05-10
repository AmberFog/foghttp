use super::active::ActiveAsyncRequest;
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};

#[derive(Clone, Default)]
pub struct AsyncRequestRegistry {
    active: Arc<Mutex<HashMap<u64, ActiveAsyncRequest>>>,
    next_request_id: Arc<AtomicU64>,
}

impl AsyncRequestRegistry {
    pub fn abort_all(&self) {
        let active_requests = {
            let mut active = self.active_requests();
            active
                .drain()
                .map(|(_id, request)| request)
                .collect::<Vec<_>>()
        };

        for request in active_requests {
            request.abort_and_cancel_python();
        }
    }

    pub(super) fn abort_request(&self, request_id: u64) {
        if let Some(request) = self.remove(request_id) {
            request.abort();
        }
    }

    pub(super) fn insert(&self, request_id: u64, request: ActiveAsyncRequest) {
        self.active_requests().insert(request_id, request);
    }

    pub(super) fn next_request_id(&self) -> u64 {
        self.next_request_id.fetch_add(1, Ordering::Relaxed)
    }

    pub(super) fn remove(&self, request_id: u64) -> Option<ActiveAsyncRequest> {
        self.active_requests().remove(&request_id)
    }

    fn active_requests(&self) -> MutexGuard<'_, HashMap<u64, ActiveAsyncRequest>> {
        self.active
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}
