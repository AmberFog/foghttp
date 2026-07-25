use std::collections::VecDeque;
use std::future::Future;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::mpsc::{sync_channel, Receiver, SyncSender, TrySendError};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError, Weak};
use std::thread;
use std::time::{Duration, Instant};

const NATIVE_TELEMETRY_JOURNAL_CAPACITY: usize = 4_096;

tokio::task_local! {
    static REQUEST_TELEMETRY: RequestTelemetry;
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum TelemetryEventType {
    PoolAcquireStarted,
    PoolAcquireFinished,
    ConnectionOpened,
    ConnectionOpenFailed,
    ConnectionReused,
    ConnectionClosed,
    ConnectionAborted,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum TelemetryRequestMode {
    Buffered,
    Stream,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum TelemetryOutcome {
    Success,
    Error,
    Closed,
    Cancelled,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum TelemetryErrorType {
    RequestError,
    NetworkError,
    PoolTimeout,
    SsrfError,
    TimeoutError,
    ReadTimeout,
    ResponseBodyBudgetExceededError,
    ResponseBodyTooLargeError,
    WriteTimeout,
    CancelledError,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct TelemetryEventRecord {
    pub event_type: TelemetryEventType,
    pub request_id: Option<u64>,
    pub mode: Option<TelemetryRequestMode>,
    pub method: Option<String>,
    pub origin: Option<String>,
    pub elapsed: Option<Duration>,
    pub redirect_hop: Option<usize>,
    pub outcome: Option<TelemetryOutcome>,
    pub error_type: Option<TelemetryErrorType>,
}

#[derive(Debug, Default)]
pub(crate) struct TelemetryEventBatch {
    pub events: Vec<TelemetryEventRecord>,
    pub dropped_events: u64,
}

#[derive(Clone)]
pub(crate) struct ClientTelemetry {
    inner: Arc<ClientTelemetryInner>,
}

struct ClientTelemetryInner {
    sender: SyncSender<TelemetryEventRecord>,
    journal: Mutex<TelemetryJournal>,
    capacity: usize,
    queued_events: AtomicUsize,
    dropped_events: AtomicU64,
    closed: AtomicBool,
    active_producers: AtomicUsize,
    connections: Mutex<Vec<Weak<ConnectionEventTelemetryInner>>>,
    pending_opens: Mutex<Vec<Arc<ConnectionOpenTelemetryInner>>>,
}

struct TelemetryProducer<'a> {
    inner: &'a ClientTelemetryInner,
}

struct TelemetryJournal {
    receiver: Receiver<TelemetryEventRecord>,
    retained: VecDeque<TelemetryEventRecord>,
}

#[derive(Clone)]
pub(crate) struct RequestTelemetry {
    client: ClientTelemetry,
    request_id: u64,
    mode: TelemetryRequestMode,
    method: Arc<str>,
    redirect_hop: Arc<AtomicUsize>,
    connection_assignment: Arc<Mutex<()>>,
    state: Arc<Mutex<RequestState>>,
}

#[derive(Clone)]
pub(crate) struct RequestConnectionUseTelemetry {
    request: RequestTelemetry,
    token: Arc<ConnectionUseToken>,
}

#[derive(Clone)]
pub(crate) struct ConnectionEventTelemetry {
    inner: Arc<ConnectionEventTelemetryInner>,
}

pub(crate) struct ConnectionOpenTelemetry {
    inner: Arc<ConnectionOpenTelemetryInner>,
}

struct ConnectionOpenTelemetryInner {
    client: ClientTelemetry,
    origin: Option<String>,
    request: Option<RequestTelemetry>,
    started: Instant,
    finished: AtomicBool,
}

struct ConnectionEventTelemetryInner {
    client: ClientTelemetry,
    origin: Option<String>,
    closed: AtomicBool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ActivePhaseType {
    PoolAcquire,
}

struct ActivePhase {
    phase_type: ActivePhaseType,
    origin: String,
    redirect_hop: usize,
    started: Instant,
}

struct ActiveConnectionUse {
    token: Arc<ConnectionUseToken>,
    origin: String,
    redirect_hop: usize,
}

struct ConnectionUseToken;

#[derive(Default)]
struct RequestState {
    active: Option<ActivePhase>,
    connection_use: Option<ActiveConnectionUse>,
    cancelled: bool,
    terminal_error_type: Option<TelemetryErrorType>,
}

impl ClientTelemetry {
    pub(crate) fn new() -> Self {
        Self::with_capacity(NATIVE_TELEMETRY_JOURNAL_CAPACITY)
    }

    fn with_capacity(capacity: usize) -> Self {
        let (sender, receiver) = sync_channel(capacity);
        Self {
            inner: Arc::new(ClientTelemetryInner {
                sender,
                journal: Mutex::new(TelemetryJournal {
                    receiver,
                    retained: VecDeque::new(),
                }),
                capacity,
                queued_events: AtomicUsize::new(0),
                dropped_events: AtomicU64::new(0),
                closed: AtomicBool::new(false),
                active_producers: AtomicUsize::new(0),
                connections: Mutex::new(Vec::new()),
                pending_opens: Mutex::new(Vec::new()),
            }),
        }
    }

    pub(crate) fn request(
        &self,
        request_id: u64,
        mode: TelemetryRequestMode,
        method: String,
    ) -> RequestTelemetry {
        RequestTelemetry {
            client: self.clone(),
            request_id,
            mode,
            method: Arc::from(method),
            redirect_hop: Arc::new(AtomicUsize::new(0)),
            connection_assignment: Arc::new(Mutex::new(())),
            state: Arc::new(Mutex::new(RequestState::default())),
        }
    }

    pub(crate) fn connection_open(
        &self,
        origin: Option<String>,
        request: Option<RequestTelemetry>,
    ) -> ConnectionOpenTelemetry {
        let inner = Arc::new(ConnectionOpenTelemetryInner {
            client: self.clone(),
            origin,
            request,
            started: Instant::now(),
            finished: AtomicBool::new(false),
        });
        let mut pending_opens = self.lock_pending_opens();
        pending_opens.retain(|pending| !pending.finished.load(Ordering::Acquire));
        if self.inner.closed.load(Ordering::Acquire) {
            inner.finished.store(true, Ordering::Release);
        } else {
            // Strong ownership lets shutdown claim an open whose connector future drops after seal.
            pending_opens.push(Arc::clone(&inner));
        }
        drop(pending_opens);
        ConnectionOpenTelemetry { inner }
    }

    fn opened_connection(
        &self,
        open: &Arc<ConnectionOpenTelemetryInner>,
    ) -> Option<ConnectionEventTelemetry> {
        let _producer = self.try_begin_production()?;
        let mut connections = self.lock_connections();
        if self.inner.closed.load(Ordering::Acquire) || open.finished.swap(true, Ordering::AcqRel) {
            return None;
        }
        let origin = open.origin.clone();
        let connection = ConnectionEventTelemetry {
            inner: Arc::new(ConnectionEventTelemetryInner {
                client: self.clone(),
                origin: origin.clone(),
                closed: AtomicBool::new(false),
            }),
        };
        connections.retain(|connection| connection.strong_count() > 0);
        connections.push(Arc::downgrade(&connection.inner));
        self.record_unchecked(TelemetryEventRecord {
            event_type: TelemetryEventType::ConnectionOpened,
            request_id: None,
            mode: None,
            method: None,
            origin,
            elapsed: Some(open.started.elapsed()),
            redirect_hop: None,
            outcome: Some(TelemetryOutcome::Success),
            error_type: None,
        });
        Some(connection)
    }

    pub(crate) fn close_connections(&self) {
        let (connections, pending_opens) = {
            let mut registered = self.lock_connections();
            let mut pending = self.lock_pending_opens();
            self.inner.closed.store(true, Ordering::Release);
            let connections = registered
                .iter()
                .filter_map(Weak::upgrade)
                .collect::<Vec<_>>();
            let pending_opens = std::mem::take(&mut *pending);
            registered.clear();
            (connections, pending_opens)
        };
        while self.inner.active_producers.load(Ordering::Acquire) != 0 {
            thread::yield_now();
        }
        for pending_open in pending_opens {
            pending_open.finish_after_seal();
        }
        for connection in connections {
            ConnectionEventTelemetry { inner: connection }.closed_after_seal();
        }
    }

    fn record_connection_open_failed_unchecked(
        &self,
        origin: Option<String>,
        elapsed: Duration,
        error_type: TelemetryErrorType,
    ) {
        self.record_unchecked(TelemetryEventRecord {
            event_type: TelemetryEventType::ConnectionOpenFailed,
            request_id: None,
            mode: None,
            method: None,
            origin,
            elapsed: Some(elapsed),
            redirect_hop: None,
            outcome: Some(if error_type == TelemetryErrorType::CancelledError {
                TelemetryOutcome::Cancelled
            } else {
                TelemetryOutcome::Error
            }),
            error_type: Some(error_type),
        });
    }

    fn connection_closed_after_seal(&self, origin: Option<String>) {
        self.record_unchecked(TelemetryEventRecord {
            event_type: TelemetryEventType::ConnectionClosed,
            request_id: None,
            mode: None,
            method: None,
            origin,
            elapsed: None,
            redirect_hop: None,
            outcome: Some(TelemetryOutcome::Closed),
            error_type: None,
        });
    }

    pub(crate) fn drain(&self, request_id: Option<u64>) -> TelemetryEventBatch {
        let events = {
            let mut journal = self.lock_journal();
            match request_id {
                Some(request_id) => journal.drain_request(request_id),
                None => journal.drain_all(),
            }
        };
        self.inner
            .queued_events
            .fetch_sub(events.len(), Ordering::Relaxed);
        let dropped_events = if request_id.is_none() {
            self.inner.dropped_events.swap(0, Ordering::Relaxed)
        } else {
            0
        };
        TelemetryEventBatch {
            events,
            dropped_events,
        }
    }

    fn record(&self, event: TelemetryEventRecord) {
        let Some(_producer) = self.try_begin_production() else {
            return;
        };
        self.record_unchecked(event);
    }

    fn record_unchecked(&self, event: TelemetryEventRecord) {
        if !self.reserve_event_slot() {
            self.note_dropped_event();
            return;
        }
        match self.inner.sender.try_send(event) {
            Ok(()) => {}
            Err(TrySendError::Full(_event)) => {
                self.release_event_slot();
                self.note_dropped_event();
            }
            Err(TrySendError::Disconnected(_event)) => self.release_event_slot(),
        }
    }

    fn try_begin_production(&self) -> Option<TelemetryProducer<'_>> {
        if self.inner.closed.load(Ordering::Acquire) {
            return None;
        }
        self.inner.active_producers.fetch_add(1, Ordering::AcqRel);
        if self.inner.closed.load(Ordering::Acquire) {
            self.inner.active_producers.fetch_sub(1, Ordering::Release);
            return None;
        }
        Some(TelemetryProducer { inner: &self.inner })
    }

    fn reserve_event_slot(&self) -> bool {
        self.inner
            .queued_events
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |queued| {
                (queued < self.inner.capacity).then_some(queued + 1)
            })
            .is_ok()
    }

    fn release_event_slot(&self) {
        self.inner.queued_events.fetch_sub(1, Ordering::Relaxed);
    }

    fn note_dropped_event(&self) {
        self.inner.dropped_events.fetch_add(1, Ordering::Relaxed);
    }

    fn lock_journal(&self) -> MutexGuard<'_, TelemetryJournal> {
        self.inner
            .journal
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }

    fn lock_connections(&self) -> MutexGuard<'_, Vec<Weak<ConnectionEventTelemetryInner>>> {
        self.inner
            .connections
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }

    fn lock_pending_opens(&self) -> MutexGuard<'_, Vec<Arc<ConnectionOpenTelemetryInner>>> {
        self.inner
            .pending_opens
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }
}

impl Drop for TelemetryProducer<'_> {
    fn drop(&mut self) {
        self.inner.active_producers.fetch_sub(1, Ordering::Release);
    }
}

impl TelemetryJournal {
    fn drain_request(&mut self, request_id: u64) -> Vec<TelemetryEventRecord> {
        let mut matching = Vec::new();
        for event in std::mem::take(&mut self.retained) {
            if event.request_id.is_none() || event.request_id == Some(request_id) {
                matching.push(event);
            } else {
                self.retained.push_back(event);
            }
        }
        for event in self.receiver.try_iter() {
            if event.request_id.is_none() || event.request_id == Some(request_id) {
                matching.push(event);
            } else {
                self.retained.push_back(event);
            }
        }
        matching
    }

    fn drain_all(&mut self) -> Vec<TelemetryEventRecord> {
        self.retained
            .drain(..)
            .chain(self.receiver.try_iter())
            .collect()
    }
}

impl ConnectionEventTelemetry {
    pub(crate) fn closed(&self) {
        let Some(_producer) = self.inner.client.try_begin_production() else {
            return;
        };
        if self.inner.closed.swap(true, Ordering::AcqRel) {
            return;
        }
        self.inner.client.record_unchecked(TelemetryEventRecord {
            event_type: TelemetryEventType::ConnectionClosed,
            request_id: None,
            mode: None,
            method: None,
            origin: self.inner.origin.clone(),
            elapsed: None,
            redirect_hop: None,
            outcome: Some(TelemetryOutcome::Closed),
            error_type: None,
        });
    }

    fn closed_after_seal(&self) {
        if self.inner.closed.swap(true, Ordering::AcqRel) {
            return;
        }
        self.inner
            .client
            .connection_closed_after_seal(self.inner.origin.clone());
    }
}

impl ConnectionOpenTelemetry {
    pub(crate) fn opened(self) -> Option<ConnectionEventTelemetry> {
        self.inner.client.opened_connection(&self.inner)
    }

    pub(crate) fn failed(self, error_type: TelemetryErrorType) {
        self.inner.finish_before_seal(error_type);
    }
}

impl Drop for ConnectionOpenTelemetry {
    fn drop(&mut self) {
        self.inner
            .finish_before_seal(self.inner.terminal_error_type());
    }
}

impl ConnectionOpenTelemetryInner {
    fn finish_before_seal(&self, error_type: TelemetryErrorType) {
        let Some(_producer) = self.client.try_begin_production() else {
            return;
        };
        if self.finished.swap(true, Ordering::AcqRel) {
            return;
        }
        self.client.record_connection_open_failed_unchecked(
            self.origin.clone(),
            self.started.elapsed(),
            error_type,
        );
    }

    fn finish_after_seal(&self) {
        if self.finished.swap(true, Ordering::AcqRel) {
            return;
        }
        self.client.record_connection_open_failed_unchecked(
            self.origin.clone(),
            self.started.elapsed(),
            self.terminal_error_type(),
        );
    }

    fn terminal_error_type(&self) -> TelemetryErrorType {
        self.request
            .as_ref()
            .and_then(RequestTelemetry::terminal_error_type)
            .unwrap_or(TelemetryErrorType::CancelledError)
    }
}

impl RequestTelemetry {
    pub(crate) fn begin_pool_acquire(&self, origin: &str, redirect_hop: usize) {
        self.redirect_hop.store(redirect_hop, Ordering::Relaxed);
        self.begin_phase(ActivePhaseType::PoolAcquire, origin, redirect_hop, true);
    }

    pub(crate) fn finish_pool_acquire_success(&self) {
        self.finish_phase(
            ActivePhaseType::PoolAcquire,
            TelemetryEventType::PoolAcquireFinished,
            TelemetryOutcome::Success,
            None,
        );
    }

    pub(crate) fn finish_pool_acquire_error(&self, error_type: TelemetryErrorType) {
        self.finish_phase(
            ActivePhaseType::PoolAcquire,
            TelemetryEventType::PoolAcquireFinished,
            TelemetryOutcome::Error,
            Some(error_type),
        );
    }

    pub(crate) fn connection_aborted(
        &self,
        origin: &str,
        redirect_hop: usize,
        outcome: TelemetryOutcome,
        error_type: Option<TelemetryErrorType>,
    ) {
        self.client.record(self.event(
            TelemetryEventType::ConnectionAborted,
            origin,
            redirect_hop,
            None,
            Some(outcome),
            error_type,
        ));
    }

    pub(crate) fn begin_connection_use(
        &self,
        origin: &str,
        reused: bool,
    ) -> Option<RequestConnectionUseTelemetry> {
        let token = Arc::new(ConnectionUseToken);
        let mut state = self.lock_state();
        let redirect_hop = self.current_redirect_hop();
        if state.cancelled {
            return None;
        }
        if state.connection_use.is_some() {
            debug_assert!(
                false,
                "native telemetry connection use started out of order"
            );
            return None;
        }
        if reused {
            self.client.record(self.event(
                TelemetryEventType::ConnectionReused,
                origin,
                redirect_hop,
                None,
                Some(TelemetryOutcome::Success),
                None,
            ));
        }
        state.connection_use = Some(ActiveConnectionUse {
            token: Arc::clone(&token),
            origin: origin.to_owned(),
            redirect_hop,
        });
        Some(RequestConnectionUseTelemetry {
            request: self.clone(),
            token,
        })
    }

    pub(crate) fn current_redirect_hop(&self) -> usize {
        self.redirect_hop.load(Ordering::Relaxed)
    }

    pub(crate) fn cancel(&self) {
        let _assignment = self.lock_connection_assignment();
        let mut state = self.lock_state();
        if state.cancelled {
            return;
        }
        state.cancelled = true;
        state.terminal_error_type = Some(TelemetryErrorType::CancelledError);
        let phase = state.active.take();
        let connection_use = state.connection_use.take();
        if let Some(phase) = phase {
            self.record_finished_phase(
                &phase,
                TelemetryOutcome::Cancelled,
                TelemetryErrorType::CancelledError,
            );
        }
        if let Some(connection_use) = connection_use {
            self.connection_aborted(
                &connection_use.origin,
                connection_use.redirect_hop,
                TelemetryOutcome::Cancelled,
                Some(TelemetryErrorType::CancelledError),
            );
        }
    }

    pub(crate) fn finish_active_phase_error(&self, error_type: TelemetryErrorType) {
        let mut state = self.lock_state();
        if state.cancelled {
            return;
        }
        state.terminal_error_type = Some(error_type);
        if let Some(phase) = state.active.take() {
            self.record_finished_phase(&phase, TelemetryOutcome::Error, error_type);
        }
    }

    fn record_finished_phase(
        &self,
        phase: &ActivePhase,
        outcome: TelemetryOutcome,
        error_type: TelemetryErrorType,
    ) {
        let event_type = match phase.phase_type {
            ActivePhaseType::PoolAcquire => TelemetryEventType::PoolAcquireFinished,
        };
        self.client.record(self.event(
            event_type,
            &phase.origin,
            phase.redirect_hop,
            Some(phase.started.elapsed()),
            Some(outcome),
            Some(error_type),
        ));
    }

    fn finish_connection_use(
        &self,
        token: &Arc<ConnectionUseToken>,
        terminal: Option<(TelemetryOutcome, Option<TelemetryErrorType>)>,
    ) -> bool {
        let mut state = self.lock_state();
        if !state
            .connection_use
            .as_ref()
            .is_some_and(|active| Arc::ptr_eq(&active.token, token))
        {
            return false;
        }
        let connection_use = state.connection_use.take();
        let Some(connection_use) = connection_use else {
            return false;
        };
        if let Some((outcome, error_type)) = terminal {
            self.connection_aborted(
                &connection_use.origin,
                connection_use.redirect_hop,
                outcome,
                error_type,
            );
        }
        true
    }

    pub(crate) fn abort_active_connection_use(
        &self,
        outcome: TelemetryOutcome,
        error_type: Option<TelemetryErrorType>,
    ) -> bool {
        let mut state = self.lock_state();
        let Some(connection_use) = state.connection_use.take() else {
            return false;
        };
        self.connection_aborted(
            &connection_use.origin,
            connection_use.redirect_hop,
            outcome,
            error_type,
        );
        true
    }

    fn begin_phase(
        &self,
        phase_type: ActivePhaseType,
        origin: &str,
        redirect_hop: usize,
        emit_started: bool,
    ) {
        let mut state = self.lock_state();
        if state.cancelled {
            return;
        }
        if state.active.is_some() {
            debug_assert!(false, "native telemetry phase started out of order");
            return;
        }
        state.active = Some(ActivePhase {
            phase_type,
            origin: origin.to_owned(),
            redirect_hop,
            started: Instant::now(),
        });
        if emit_started {
            self.client.record(self.event(
                TelemetryEventType::PoolAcquireStarted,
                origin,
                redirect_hop,
                None,
                None,
                None,
            ));
        }
    }

    fn finish_phase(
        &self,
        phase_type: ActivePhaseType,
        event_type: TelemetryEventType,
        outcome: TelemetryOutcome,
        error_type: Option<TelemetryErrorType>,
    ) -> bool {
        let mut state = self.lock_state();
        if state
            .active
            .as_ref()
            .is_some_and(|phase| phase.phase_type != phase_type)
        {
            debug_assert!(false, "native telemetry phase finished out of order");
            return false;
        }
        let Some(phase) = state.active.take() else {
            return false;
        };
        self.client.record(self.event(
            event_type,
            &phase.origin,
            phase.redirect_hop,
            Some(phase.started.elapsed()),
            Some(outcome),
            error_type,
        ));
        true
    }

    fn event(
        &self,
        event_type: TelemetryEventType,
        origin: &str,
        redirect_hop: usize,
        elapsed: Option<Duration>,
        outcome: Option<TelemetryOutcome>,
        error_type: Option<TelemetryErrorType>,
    ) -> TelemetryEventRecord {
        TelemetryEventRecord {
            event_type,
            request_id: Some(self.request_id),
            mode: Some(self.mode),
            method: Some(self.method.to_string()),
            origin: Some(origin.to_owned()),
            elapsed,
            redirect_hop: Some(redirect_hop),
            outcome,
            error_type,
        }
    }

    fn lock_state(&self) -> MutexGuard<'_, RequestState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }

    pub(crate) fn lock_connection_assignment(&self) -> MutexGuard<'_, ()> {
        self.connection_assignment
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }

    pub(crate) fn is_cancelled(&self) -> bool {
        self.lock_state().cancelled
    }

    fn terminal_error_type(&self) -> Option<TelemetryErrorType> {
        self.lock_state().terminal_error_type
    }
}

impl RequestConnectionUseTelemetry {
    pub(crate) fn finish(&self) -> bool {
        self.request.finish_connection_use(&self.token, None)
    }

    pub(crate) fn abort(
        &self,
        outcome: TelemetryOutcome,
        error_type: Option<TelemetryErrorType>,
    ) -> bool {
        self.request
            .finish_connection_use(&self.token, Some((outcome, error_type)))
    }
}

pub(crate) async fn with_request_telemetry<F>(
    telemetry: Option<RequestTelemetry>,
    future: F,
) -> F::Output
where
    F: Future,
{
    match telemetry {
        Some(telemetry) => REQUEST_TELEMETRY.scope(telemetry, future).await,
        None => future.await,
    }
}

pub(crate) fn current_request_telemetry() -> Option<RequestTelemetry> {
    REQUEST_TELEMETRY.try_with(Clone::clone).ok()
}

impl TelemetryEventType {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::PoolAcquireStarted => "pool_acquire_started",
            Self::PoolAcquireFinished => "pool_acquire_finished",
            Self::ConnectionOpened => "connection_opened",
            Self::ConnectionOpenFailed => "connection_open_failed",
            Self::ConnectionReused => "connection_reused",
            Self::ConnectionClosed => "connection_closed",
            Self::ConnectionAborted => "connection_aborted",
        }
    }
}

impl TelemetryRequestMode {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::Buffered => "buffered",
            Self::Stream => "stream",
        }
    }
}

impl TelemetryOutcome {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::Success => "success",
            Self::Error => "error",
            Self::Closed => "closed",
            Self::Cancelled => "cancelled",
        }
    }
}

impl TelemetryErrorType {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::RequestError => "RequestError",
            Self::NetworkError => "NetworkError",
            Self::PoolTimeout => "PoolTimeout",
            Self::SsrfError => "SSRFError",
            Self::TimeoutError => "TimeoutError",
            Self::ReadTimeout => "ReadTimeout",
            Self::ResponseBodyBudgetExceededError => "ResponseBodyBudgetExceededError",
            Self::ResponseBodyTooLargeError => "ResponseBodyTooLargeError",
            Self::WriteTimeout => "WriteTimeout",
            Self::CancelledError => "CancelledError",
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{
        ClientTelemetry, TelemetryErrorType, TelemetryEventRecord, TelemetryEventType,
        TelemetryOutcome, TelemetryRequestMode,
    };
    use std::sync::atomic::Ordering;
    use std::sync::mpsc::channel;
    use std::thread;

    const ORIGIN: &str = "https://example.com";

    #[test]
    fn journal_is_bounded_and_reports_drops_once() {
        let telemetry = ClientTelemetry::with_capacity(1);
        let request = telemetry.request(1, TelemetryRequestMode::Buffered, "GET".to_owned());

        request.begin_pool_acquire(ORIGIN, 0);
        request.finish_pool_acquire_success();

        let first = telemetry.drain(None);
        assert_eq!(first.events.len(), 1);
        assert_eq!(first.dropped_events, 1);
        assert_eq!(telemetry.drain(None).dropped_events, 0);
    }

    #[test]
    fn cancellation_finishes_active_pool_phase_once() {
        let telemetry = ClientTelemetry::with_capacity(4);
        let request = telemetry.request(7, TelemetryRequestMode::Stream, "GET".to_owned());

        request.begin_pool_acquire(ORIGIN, 2);
        request.cancel();
        request.finish_pool_acquire_error(TelemetryErrorType::PoolTimeout);

        let batch = telemetry.drain(Some(7));
        assert_eq!(batch.dropped_events, 0);
        assert_eq!(batch.events.len(), 2);
        assert_eq!(
            batch.events[0].event_type,
            TelemetryEventType::PoolAcquireStarted
        );
        assert_eq!(batch.events[0].outcome, None);
        assert_eq!(
            batch.events[1].event_type,
            TelemetryEventType::PoolAcquireFinished
        );
        assert_eq!(batch.events[1].outcome, Some(TelemetryOutcome::Cancelled));
        assert_eq!(
            batch.events[1].error_type,
            Some(TelemetryErrorType::CancelledError)
        );
    }

    #[test]
    fn cancellation_prevents_a_late_phase_from_starting() {
        let telemetry = ClientTelemetry::with_capacity(2);
        let request = telemetry.request(7, TelemetryRequestMode::Buffered, "GET".to_owned());

        request.cancel();
        request.begin_pool_acquire(ORIGIN, 0);
        request.finish_pool_acquire_success();

        let batch = telemetry.drain(Some(7));
        assert!(batch.events.is_empty());
        assert_eq!(batch.dropped_events, 0);
    }

    #[test]
    fn cancellation_finishes_active_connection_use_before_drain() {
        let telemetry = ClientTelemetry::with_capacity(2);
        let request = telemetry.request(7, TelemetryRequestMode::Buffered, "GET".to_owned());
        let connection_use = request
            .begin_connection_use(ORIGIN, false)
            .expect("connection use starts before cancellation");

        request.cancel();
        assert!(!connection_use.abort(
            TelemetryOutcome::Error,
            Some(TelemetryErrorType::ReadTimeout),
        ));

        let batch = telemetry.drain(Some(7));
        assert_eq!(batch.events.len(), 1);
        assert_eq!(
            batch.events[0].event_type,
            TelemetryEventType::ConnectionAborted
        );
        assert_eq!(batch.events[0].outcome, Some(TelemetryOutcome::Cancelled));
        assert_eq!(
            batch.events[0].error_type,
            Some(TelemetryErrorType::CancelledError),
        );
    }

    #[test]
    fn connection_use_started_after_cancellation_cannot_emit_reuse_or_abort() {
        let telemetry = ClientTelemetry::with_capacity(1);
        let request = telemetry.request(7, TelemetryRequestMode::Buffered, "GET".to_owned());

        request.cancel();
        assert!(request.begin_connection_use(ORIGIN, true).is_none());

        assert!(telemetry.drain(Some(7)).events.is_empty());
    }

    #[test]
    fn cancellation_claims_connection_use_after_an_in_flight_assignment() {
        let telemetry = ClientTelemetry::with_capacity(1);
        let request = telemetry.request(7, TelemetryRequestMode::Buffered, "GET".to_owned());
        let assignment = request.lock_connection_assignment();
        let cancelling_request = request.clone();
        let (waiting_sender, waiting_receiver) = channel();
        let cancellation = thread::spawn(move || {
            assert!(cancelling_request.connection_assignment.try_lock().is_err());
            waiting_sender
                .send(())
                .expect("assignment wait signal remains connected");
            cancelling_request.cancel();
        });
        waiting_receiver
            .recv()
            .expect("cancellation reached the assignment transition");

        let connection_use = request
            .begin_connection_use(ORIGIN, false)
            .expect("assignment started before cancellation");
        drop(assignment);
        cancellation.join().expect("cancellation thread");

        assert!(!connection_use.finish());
        let batch = telemetry.drain(Some(7));
        assert_eq!(batch.events.len(), 1);
        assert_eq!(
            batch.events[0].event_type,
            TelemetryEventType::ConnectionAborted
        );
        assert_eq!(batch.events[0].outcome, Some(TelemetryOutcome::Cancelled));
    }

    #[test]
    fn completed_connection_use_is_not_reclassified_by_late_cancellation() {
        let telemetry = ClientTelemetry::with_capacity(1);
        let request = telemetry.request(7, TelemetryRequestMode::Buffered, "GET".to_owned());
        let connection_use = request
            .begin_connection_use(ORIGIN, false)
            .expect("connection use starts before completion");

        assert!(connection_use.finish());
        request.cancel();

        assert!(telemetry.drain(Some(7)).events.is_empty());
    }

    #[test]
    fn connection_close_is_client_scoped() {
        let telemetry = ClientTelemetry::with_capacity(2);

        telemetry
            .connection_open(Some(ORIGIN.to_owned()), None)
            .opened()
            .expect("connection telemetry remains open")
            .closed();

        let event = telemetry
            .drain(None)
            .events
            .into_iter()
            .find(|event| event.event_type == TelemetryEventType::ConnectionClosed)
            .expect("connection close event");
        assert_eq!(event.event_type, TelemetryEventType::ConnectionClosed);
        assert_eq!(event.request_id, None);
        assert_eq!(event.mode, None);
        assert_eq!(event.method, None);
        assert_eq!(event.origin.as_deref(), Some(ORIGIN));
        assert_eq!(event.outcome, Some(TelemetryOutcome::Closed));
    }

    #[test]
    fn client_shutdown_closes_registered_connections_once() {
        let telemetry = ClientTelemetry::with_capacity(4);
        let first = telemetry
            .connection_open(Some(ORIGIN.to_owned()), None)
            .opened()
            .expect("first connection telemetry");
        let second = telemetry
            .connection_open(Some(ORIGIN.to_owned()), None)
            .opened()
            .expect("second connection telemetry");

        telemetry.close_connections();
        first.closed();
        second.closed();

        let batch = telemetry.drain(None);
        assert_eq!(batch.events.len(), 4);
        assert_eq!(
            batch
                .events
                .iter()
                .filter(|event| event.event_type == TelemetryEventType::ConnectionClosed)
                .count(),
            2
        );
    }

    #[test]
    fn client_shutdown_finishes_pending_connection_open_once() {
        let telemetry = ClientTelemetry::with_capacity(2);
        let request = telemetry.request(7, TelemetryRequestMode::Buffered, "GET".to_owned());
        let pending_open =
            telemetry.connection_open(Some(ORIGIN.to_owned()), Some(request.clone()));

        request.cancel();
        request.finish_active_phase_error(TelemetryErrorType::TimeoutError);
        telemetry.close_connections();
        drop(pending_open);

        let batch = telemetry.drain(None);
        assert_eq!(batch.events.len(), 1);
        assert_eq!(
            batch.events[0].event_type,
            TelemetryEventType::ConnectionOpenFailed
        );
        assert_eq!(batch.events[0].outcome, Some(TelemetryOutcome::Cancelled));
        assert_eq!(
            batch.events[0].error_type,
            Some(TelemetryErrorType::CancelledError)
        );
    }

    #[test]
    fn connection_open_failure_before_shutdown_is_not_duplicated() {
        let telemetry = ClientTelemetry::with_capacity(2);

        telemetry
            .connection_open(Some(ORIGIN.to_owned()), None)
            .failed(TelemetryErrorType::NetworkError);
        telemetry.close_connections();

        let batch = telemetry.drain(None);
        assert_eq!(batch.events.len(), 1);
        assert_eq!(
            batch.events[0].event_type,
            TelemetryEventType::ConnectionOpenFailed
        );
        assert_eq!(batch.events[0].outcome, Some(TelemetryOutcome::Error));
        assert_eq!(
            batch.events[0].error_type,
            Some(TelemetryErrorType::NetworkError)
        );
    }

    #[test]
    fn request_drain_claims_client_scoped_records_and_retains_foreign_requests() {
        let telemetry = ClientTelemetry::with_capacity(4);
        let first = telemetry.request(1, TelemetryRequestMode::Buffered, "GET".to_owned());
        let second = telemetry.request(2, TelemetryRequestMode::Stream, "POST".to_owned());

        let connection = telemetry
            .connection_open(Some(ORIGIN.to_owned()), None)
            .opened()
            .expect("connection telemetry");
        let _ = telemetry.drain(None);
        connection.closed();
        first.begin_pool_acquire(ORIGIN, 0);
        second.begin_pool_acquire(ORIGIN, 0);

        let first_batch = telemetry.drain(Some(1));
        assert_eq!(first_batch.events.len(), 2);
        assert!(first_batch
            .events
            .iter()
            .any(|event| event.request_id == Some(1)));
        assert!(first_batch
            .events
            .iter()
            .any(|event| event.request_id.is_none()));
        assert_eq!(first_batch.dropped_events, 0);

        let second_batch = telemetry.drain(Some(2));
        assert_eq!(second_batch.events.len(), 1);
        assert_eq!(second_batch.events[0].request_id, Some(2));
        assert_eq!(second_batch.dropped_events, 0);

        let client_batch = telemetry.drain(None);
        assert!(client_batch.events.is_empty());
    }

    #[test]
    fn claimed_client_records_cannot_starve_later_request_events() {
        let telemetry = ClientTelemetry::with_capacity(2);
        let first = telemetry.request(1, TelemetryRequestMode::Buffered, "GET".to_owned());
        let second = telemetry.request(2, TelemetryRequestMode::Buffered, "GET".to_owned());

        let connection = telemetry
            .connection_open(Some(ORIGIN.to_owned()), None)
            .opened()
            .expect("connection telemetry");
        let _ = telemetry.drain(None);
        connection.closed();
        first.begin_pool_acquire(ORIGIN, 0);
        let first_batch = telemetry.drain(Some(1));
        assert_eq!(first_batch.events.len(), 2);
        assert!(first_batch
            .events
            .iter()
            .any(|event| event.event_type == TelemetryEventType::ConnectionClosed));

        second.begin_pool_acquire(ORIGIN, 0);
        second.finish_pool_acquire_success();

        assert_eq!(telemetry.drain(Some(2)).events.len(), 2);
        let final_batch = telemetry.drain(None);
        assert!(final_batch.events.is_empty());
        assert_eq!(final_batch.dropped_events, 0);
    }

    #[test]
    fn shutdown_waits_for_in_flight_producers_and_rejects_late_records() {
        let telemetry = ClientTelemetry::with_capacity(2);
        let producer = telemetry
            .try_begin_production()
            .expect("producer starts before shutdown");
        let closing_telemetry = telemetry.clone();
        let close = thread::spawn(move || closing_telemetry.close_connections());

        while !telemetry.inner.closed.load(Ordering::Acquire) {
            thread::yield_now();
        }
        telemetry.record_unchecked(TelemetryEventRecord {
            event_type: TelemetryEventType::PoolAcquireStarted,
            request_id: Some(1),
            mode: Some(TelemetryRequestMode::Buffered),
            method: Some("GET".to_owned()),
            origin: Some(ORIGIN.to_owned()),
            elapsed: None,
            redirect_hop: Some(0),
            outcome: None,
            error_type: None,
        });
        drop(producer);
        close.join().expect("telemetry shutdown thread");

        assert_eq!(telemetry.drain(None).events.len(), 1);
        telemetry
            .request(2, TelemetryRequestMode::Buffered, "GET".to_owned())
            .begin_pool_acquire(ORIGIN, 0);
        assert!(telemetry.drain(None).events.is_empty());
    }
}
