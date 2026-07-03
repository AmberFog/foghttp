use crate::core::metrics::{Metrics, OriginMetrics, PendingRequestBlockingReason};
use crate::errors::FogHttpError;
use pyo3::prelude::*;
use std::collections::VecDeque;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use std::time::Instant;
use tokio::sync::{Notify, OwnedSemaphorePermit, Semaphore, TryAcquireError};

pub struct PendingAcquireRejected;

pub struct AcquiredPermits {
    pub global: OwnedSemaphorePermit,
    pub origin: Option<OwnedSemaphorePermit>,
}

pub enum ImmediateAcquire {
    Acquired(AcquiredPermits),
    Queue { queue_was_empty: bool },
}

pub struct PendingQueue {
    state: Mutex<PendingQueueState>,
}

struct PendingQueueState {
    next_waiter_id: u64,
    waiters: VecDeque<Arc<PendingQueueEntry>>,
}

struct PendingQueueEntry {
    waiter_id: u64,
    notify: Notify,
}

pub struct PendingQueueWaiter {
    queue: Arc<PendingQueue>,
    entry: Arc<PendingQueueEntry>,
    pending: Option<PendingAcquire>,
    queued: bool,
}

struct PendingAcquire {
    metrics: Arc<Metrics>,
    origin_metrics: Arc<OriginMetrics>,
    started: Instant,
    origin_waiter_id: u64,
}

impl Default for PendingQueue {
    fn default() -> Self {
        Self {
            state: Mutex::new(PendingQueueState::default()),
        }
    }
}

impl Default for PendingQueueState {
    fn default() -> Self {
        Self {
            next_waiter_id: 1,
            waiters: VecDeque::new(),
        }
    }
}

impl PendingQueue {
    pub fn try_acquire_immediate(
        &self,
        global_semaphore: Arc<Semaphore>,
        origin_semaphore: Option<Arc<Semaphore>>,
    ) -> PyResult<ImmediateAcquire> {
        let state = self.lock_state();
        if !state.waiters.is_empty() {
            return Ok(ImmediateAcquire::Queue {
                queue_was_empty: false,
            });
        }

        match try_acquire_permits(global_semaphore, origin_semaphore)? {
            Some(permits) => Ok(ImmediateAcquire::Acquired(permits)),
            None => Ok(ImmediateAcquire::Queue {
                queue_was_empty: true,
            }),
        }
    }

    pub fn try_register(
        self: &Arc<Self>,
        metrics: Arc<Metrics>,
        origin_metrics: Arc<OriginMetrics>,
        max_pending_requests: usize,
        blocked_by: PendingRequestBlockingReason,
    ) -> Result<PendingQueueWaiter, PendingAcquireRejected> {
        let mut state = self.lock_state();
        if state.waiters.len() >= max_pending_requests {
            metrics.pool_acquire_timeout();
            origin_metrics.pool_acquire_timeout();
            return Err(PendingAcquireRejected);
        }

        let waiter_id = state.next_waiter_id;
        state.next_waiter_id = state.next_waiter_id.saturating_add(1);
        let entry = Arc::new(PendingQueueEntry {
            waiter_id,
            notify: Notify::new(),
        });
        state.waiters.push_back(Arc::clone(&entry));
        let pending = PendingAcquire::start(metrics, origin_metrics, blocked_by);

        Ok(PendingQueueWaiter {
            queue: Arc::clone(self),
            entry,
            pending: Some(pending),
            queued: true,
        })
    }

    pub fn notify_capacity(&self) {
        self.notify_head();
    }

    fn try_acquire_for_waiter(
        &self,
        waiter_id: u64,
        global_semaphore: Arc<Semaphore>,
        origin_semaphore: Option<Arc<Semaphore>>,
    ) -> PyResult<Option<AcquiredPermits>> {
        let mut state = self.lock_state();
        if state
            .waiters
            .front()
            .is_none_or(|entry| entry.waiter_id != waiter_id)
        {
            return Ok(None);
        }

        let Some(permits) = try_acquire_permits(global_semaphore, origin_semaphore)? else {
            return Ok(None);
        };
        state.waiters.pop_front();
        Ok(Some(permits))
    }

    fn remove_waiter(&self, waiter_id: u64) -> bool {
        let mut state = self.lock_state();
        let Some(position) = state
            .waiters
            .iter()
            .position(|queued_waiter| queued_waiter.waiter_id == waiter_id)
        else {
            return false;
        };

        state.waiters.remove(position);
        true
    }

    fn notify_head(&self) {
        let notify = self.lock_state().waiters.front().map(Arc::clone);
        if let Some(entry) = notify {
            entry.notify.notify_one();
        }
    }

    fn lock_state(&self) -> MutexGuard<'_, PendingQueueState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

impl PendingQueueWaiter {
    pub async fn acquire_permits(
        &mut self,
        global_semaphore: Arc<Semaphore>,
        origin_semaphore: Option<Arc<Semaphore>>,
    ) -> PyResult<AcquiredPermits> {
        loop {
            let notified = self.entry.notify.notified();
            tokio::pin!(notified);
            notified.as_mut().enable();
            if let Some(permits) = self.queue.try_acquire_for_waiter(
                self.entry.waiter_id,
                Arc::clone(&global_semaphore),
                origin_semaphore.clone(),
            )? {
                self.queued = false;
                self.pending.take();
                self.queue.notify_capacity();
                return Ok(permits);
            }
            notified.await;
        }
    }
}

impl Drop for PendingQueueWaiter {
    fn drop(&mut self) {
        if self.queued && self.queue.remove_waiter(self.entry.waiter_id) {
            self.pending.take();
            self.queue.notify_capacity();
        }
    }
}

impl PendingAcquire {
    fn start(
        metrics: Arc<Metrics>,
        origin_metrics: Arc<OriginMetrics>,
        blocked_by: PendingRequestBlockingReason,
    ) -> Self {
        metrics.pending_request_registered();
        let origin_waiter_id = origin_metrics.pending_request_started(blocked_by);
        Self {
            metrics,
            origin_metrics,
            started: Instant::now(),
            origin_waiter_id,
        }
    }
}

impl Drop for PendingAcquire {
    fn drop(&mut self) {
        let elapsed = self.started.elapsed();

        self.metrics.pending_request_finished();
        self.metrics.pool_acquire_wait_finished(elapsed);
        self.origin_metrics
            .pending_request_finished(self.origin_waiter_id);
        self.origin_metrics.pool_acquire_wait_finished(elapsed);
    }
}

fn try_acquire_permits(
    global_semaphore: Arc<Semaphore>,
    origin_semaphore: Option<Arc<Semaphore>>,
) -> PyResult<Option<AcquiredPermits>> {
    let origin = match origin_semaphore {
        Some(semaphore) => match semaphore.try_acquire_owned() {
            Ok(permit) => Some(permit),
            Err(TryAcquireError::NoPermits) => return Ok(None),
            Err(TryAcquireError::Closed) => {
                return Err(FogHttpError::new_err("origin acquire gate is closed"));
            }
        },
        None => None,
    };
    let global = match global_semaphore.try_acquire_owned() {
        Ok(permit) => permit,
        Err(TryAcquireError::NoPermits) => return Ok(None),
        Err(TryAcquireError::Closed) => {
            return Err(FogHttpError::new_err("acquire gate is closed"))
        }
    };

    Ok(Some(AcquiredPermits { global, origin }))
}
