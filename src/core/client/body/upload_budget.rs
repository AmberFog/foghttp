use super::UploadBodyChannel;
use bytes::Bytes;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Condvar, Mutex, MutexGuard, Weak};

pub(crate) const DEFAULT_MAX_UPLOAD_BUFFER_BYTES: usize = 512 * 1024;
pub(crate) const DEFAULT_MAX_BUFFERED_UPLOAD_BYTES: usize = 16 * 1024 * 1024;
pub(super) const MAX_UPLOAD_CHUNK_BYTES: usize = 64 * 1024;

pub(crate) struct UploadBodyBudget {
    max_buffered_bytes: usize,
    state: Mutex<UploadBodyBudgetState>,
    ready: Condvar,
}

pub(crate) struct UploadBodyAccount {
    pub(super) budget: Arc<UploadBodyBudget>,
    pub(super) max_buffered_bytes: usize,
    pub(super) buffered_bytes: AtomicUsize,
}

struct UploadBodyBudgetState {
    buffered_bytes: usize,
    closed: bool,
    channels: Vec<Weak<UploadBodyChannel>>,
    waiters: Vec<Weak<UploadBodyChannel>>,
    #[cfg(test)]
    peak_bytes: usize,
    #[cfg(test)]
    copy_count: usize,
}

pub(super) struct UploadBufferReservation {
    account: Arc<UploadBodyAccount>,
    byte_count: usize,
}

struct BudgetedUploadData {
    data: Bytes,
    _reservation: UploadBufferReservation,
}

impl UploadBodyBudget {
    pub(crate) fn new(max_buffered_bytes: usize) -> Self {
        assert!(
            max_buffered_bytes > 0,
            "upload byte budget must be positive"
        );
        Self {
            max_buffered_bytes,
            state: Mutex::new(UploadBodyBudgetState {
                buffered_bytes: 0,
                closed: false,
                channels: Vec::new(),
                waiters: Vec::new(),
                #[cfg(test)]
                peak_bytes: 0,
                #[cfg(test)]
                copy_count: 0,
            }),
            ready: Condvar::new(),
        }
    }

    #[cfg(test)]
    pub(crate) fn buffered_bytes(&self) -> usize {
        self.state().buffered_bytes
    }

    pub(super) fn max_buffered_bytes(&self) -> usize {
        self.max_buffered_bytes
    }

    pub(super) fn is_closed(&self) -> bool {
        self.state().closed
    }

    pub(super) fn register(&self, channel: &Arc<UploadBodyChannel>) -> bool {
        let mut state = self.state();
        if state.closed {
            return false;
        }
        state.channels.retain(|channel| channel.strong_count() > 0);
        state.channels.push(Arc::downgrade(channel));
        true
    }

    pub(crate) fn close(&self) {
        let channels = {
            let mut state = self.state();
            if state.closed {
                return;
            }
            state.closed = true;
            state.waiters.clear();
            std::mem::take(&mut state.channels)
        };
        self.ready.notify_all();
        let channels = channels
            .into_iter()
            .filter_map(|channel| channel.upgrade())
            .collect::<Vec<_>>();
        for channel in &channels {
            channel.notify_budget_closed();
        }
        for channel in channels {
            channel.abort();
        }
    }

    pub(super) fn try_reserve(
        &self,
        channel: &Arc<UploadBodyChannel>,
        byte_count: usize,
    ) -> Option<UploadBufferReservation> {
        let mut state = self.state();
        if state.closed {
            return None;
        }
        if !self.has_capacity(&state, channel, byte_count) {
            state.waiters.retain(|waiter| waiter.strong_count() > 0);
            let waiter = Arc::downgrade(channel);
            if !state
                .waiters
                .iter()
                .any(|registered| registered.ptr_eq(&waiter))
            {
                state.waiters.push(waiter);
            }
            return None;
        }
        state.buffered_bytes += byte_count;
        channel
            .account
            .buffered_bytes
            .fetch_add(byte_count, Ordering::AcqRel);
        #[cfg(test)]
        {
            state.peak_bytes = state.peak_bytes.max(state.buffered_bytes);
        }
        Some(UploadBufferReservation {
            account: Arc::clone(&channel.account),
            byte_count,
        })
    }

    pub(super) fn wait_for_capacity(&self, channel: &UploadBodyChannel, byte_count: usize) {
        let mut state = self.state();
        while !state.closed
            && !channel.closed.load(Ordering::Acquire)
            && !self.has_capacity(&state, channel, byte_count)
        {
            state = self
                .ready
                .wait(state)
                .expect("upload byte budget lock poisoned");
        }
    }

    pub(super) fn notify_closed(&self) {
        let _state = self.state();
        self.ready.notify_all();
    }

    #[cfg(test)]
    pub(super) fn copy_count(&self) -> usize {
        self.state().copy_count
    }

    #[cfg(test)]
    pub(super) fn peak_bytes(&self) -> usize {
        self.state().peak_bytes
    }

    #[cfg(test)]
    pub(crate) fn waiting_channels(&self) -> usize {
        self.state().waiters.len()
    }

    fn has_capacity(
        &self,
        state: &UploadBodyBudgetState,
        channel: &UploadBodyChannel,
        byte_count: usize,
    ) -> bool {
        state
            .buffered_bytes
            .checked_add(byte_count)
            .is_some_and(|next| next <= self.max_buffered_bytes)
            && channel
                .account
                .buffered_bytes
                .load(Ordering::Acquire)
                .checked_add(byte_count)
                .is_some_and(|next| next <= channel.account.max_buffered_bytes)
    }

    fn state(&self) -> MutexGuard<'_, UploadBodyBudgetState> {
        self.state.lock().expect("upload byte budget lock poisoned")
    }
}

impl UploadBodyAccount {
    pub(crate) fn new(max_buffered_bytes: usize, budget: Arc<UploadBodyBudget>) -> Self {
        assert!(
            max_buffered_bytes > 0,
            "upload byte budget must be positive"
        );
        Self {
            budget,
            max_buffered_bytes,
            buffered_bytes: AtomicUsize::new(0),
        }
    }

    #[cfg(test)]
    pub(crate) fn buffered_bytes(&self) -> usize {
        self.buffered_bytes.load(Ordering::Acquire)
    }

    pub(crate) fn belongs_to(&self, budget: &Arc<UploadBodyBudget>) -> bool {
        Arc::ptr_eq(&self.budget, budget)
    }
}

impl UploadBufferReservation {
    pub(super) fn into_bytes(self, data: Bytes) -> Bytes {
        Bytes::from_owner(BudgetedUploadData {
            data,
            _reservation: self,
        })
    }

    #[cfg(test)]
    pub(super) fn record_copy(&self) {
        self.account.budget.state().copy_count += 1;
    }
}

impl AsRef<[u8]> for BudgetedUploadData {
    fn as_ref(&self) -> &[u8] {
        self.data.as_ref()
    }
}

impl Drop for UploadBufferReservation {
    fn drop(&mut self) {
        let waiters = {
            let mut state = self.account.budget.state();
            state.buffered_bytes -= self.byte_count;
            self.account
                .buffered_bytes
                .fetch_sub(self.byte_count, Ordering::AcqRel);
            std::mem::take(&mut state.waiters)
        };
        self.account.budget.ready.notify_all();
        for channel in waiters.into_iter().filter_map(|waiter| waiter.upgrade()) {
            channel.notify_byte_capacity();
        }
    }
}
