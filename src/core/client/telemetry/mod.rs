#[cfg(test)]
mod tests;

use super::body::RequestBodyCompletion;
use super::connection_limit::{ConnectionGate, ConnectionPermit};
use super::write_timeout::{RequestWriteTimeout, RequestWriteTimeoutContext};
use crate::core::metrics::{Metrics, OriginMetrics, ResponseBodyLifecycleOutcome};
use crate::core::policy::SsrfViolation;
use crate::core::telemetry::{
    current_request_telemetry, ClientTelemetry, ConnectionEventTelemetry, ConnectionOpenTelemetry,
    RequestConnectionUseTelemetry, RequestTelemetry, TelemetryErrorType, TelemetryOutcome,
};
use crate::core::url::HttpUrl;
use hyper::rt::{Read, ReadBufCursor, Write};
use hyper::Uri;
use hyper_util::client::legacy::connect::{Connected, Connection};
use std::future::Future;
use std::io::{Error, ErrorKind, IoSlice};
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use std::task::{Context, Poll, Waker};
use std::time::{Duration, Instant};
use tokio::time::Sleep;
use tower_service::Service;

type BoxError = Box<dyn std::error::Error + Send + Sync>;

#[derive(Clone)]
pub(crate) struct InstrumentedConnector<C> {
    inner: C,
    metrics: Arc<Metrics>,
    connection_gate: ConnectionGate,
    idle_timeout: Duration,
    native_telemetry: Option<ClientTelemetry>,
}

#[derive(Clone)]
pub(crate) struct ConnectionTelemetry {
    inner: Arc<ConnectionTelemetryInner>,
}

pub(crate) struct ConnectionUseGuard {
    telemetry: ConnectionTelemetry,
    request_telemetry: Option<RequestTelemetry>,
    request_connection_use: Option<RequestConnectionUseTelemetry>,
    use_id: usize,
    request_body_completion: Option<RequestBodyCompletion>,
    write_timeout_finished: bool,
    finished: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum ConnectionAbortReason {
    Closed,
    Cancelled,
    Error(Option<TelemetryErrorType>),
}

pub(crate) struct InstrumentedConnection<T> {
    inner: T,
    telemetry: ConnectionTelemetry,
    _connection_permit: ConnectionPermit,
}

struct ConnectionTelemetryInner {
    metrics: Arc<Metrics>,
    origin_metrics: Option<Arc<OriginMetrics>>,
    observed_uses: AtomicUsize,
    idle_since: Mutex<Option<Instant>>,
    idle_timeout: Duration,
    closed: AtomicBool,
    aborted: AtomicBool,
    io_waker: Mutex<Option<Waker>>,
    write_timeout: Mutex<WriteTimeoutState>,
    native_telemetry: Option<ConnectionEventTelemetry>,
    origin: Option<String>,
}

#[derive(Default)]
struct WriteTimeoutState {
    active: Option<ActiveRequestWriteTimeout>,
    pending_since: Option<Instant>,
    sleep: Option<Pin<Box<Sleep>>>,
    pending_waker: Option<Waker>,
}

struct ActiveRequestWriteTimeout {
    use_id: usize,
    context: Option<RequestWriteTimeoutContext>,
    request_telemetry: Option<RequestTelemetry>,
    request_body_completion: Option<RequestBodyCompletion>,
}

impl<C> InstrumentedConnector<C> {
    pub(crate) fn new(
        inner: C,
        metrics: Arc<Metrics>,
        connection_gate: ConnectionGate,
        idle_timeout: Duration,
        native_telemetry: Option<ClientTelemetry>,
    ) -> Self {
        Self {
            inner,
            metrics,
            connection_gate,
            idle_timeout,
            native_telemetry,
        }
    }
}

impl<C> Service<Uri> for InstrumentedConnector<C>
where
    C: Service<Uri>,
    C::Response: Read + Write + Connection + Unpin + Send + 'static,
    C::Future: Send + 'static,
    C::Error: Into<BoxError>,
{
    type Response = InstrumentedConnection<C::Response>;
    type Error = BoxError;
    type Future = Pin<Box<dyn Future<Output = Result<Self::Response, Self::Error>> + Send>>;

    fn poll_ready(&mut self, context: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.inner.poll_ready(context).map_err(Into::into)
    }

    fn call(&mut self, uri: Uri) -> Self::Future {
        let metrics = Arc::clone(&self.metrics);
        let connection_gate = self.connection_gate.clone();
        let idle_timeout = self.idle_timeout;
        let origin = origin_from_uri(&uri);
        let origin_metrics = origin.as_ref().map(|origin| metrics.origin_metrics(origin));
        let request_telemetry = current_request_telemetry();
        let mut native_open = self
            .native_telemetry
            .as_ref()
            .map(|telemetry| telemetry.connection_open(origin.clone(), request_telemetry.clone()));
        let future = self.inner.call(uri);

        Box::pin(async move {
            let connection_permit = match connection_gate
                .acquire(
                    origin.as_deref(),
                    Arc::clone(&metrics),
                    origin_metrics.clone(),
                )
                .await
            {
                Ok(permit) => permit,
                Err(error) => {
                    if let Some(open) = native_open.take() {
                        open.failed(TelemetryErrorType::PoolTimeout);
                    }
                    return Err(error);
                }
            };
            match future.await {
                Ok(inner) => {
                    let native_telemetry = native_open.and_then(ConnectionOpenTelemetry::opened);
                    let telemetry = ConnectionTelemetry::new_with_native_telemetry(
                        metrics,
                        origin_metrics,
                        idle_timeout,
                        native_telemetry,
                        origin,
                    );
                    Ok(InstrumentedConnection {
                        inner,
                        telemetry,
                        _connection_permit: connection_permit,
                    })
                }
                Err(error) => {
                    let error = error.into();
                    if let Some(open) = native_open {
                        open.failed(connection_open_error_type(error.as_ref()));
                    }
                    metrics.connection_open_failed();
                    if let Some(origin_metrics) = origin_metrics {
                        origin_metrics.connection_open_failed();
                    }
                    Err(error)
                }
            }
        })
    }
}

impl ConnectionTelemetry {
    #[cfg(test)]
    fn new(
        metrics: Arc<Metrics>,
        origin_metrics: Option<Arc<OriginMetrics>>,
        idle_timeout: Duration,
    ) -> Self {
        Self::new_with_native_telemetry(metrics, origin_metrics, idle_timeout, None, None)
    }

    fn new_with_native_telemetry(
        metrics: Arc<Metrics>,
        origin_metrics: Option<Arc<OriginMetrics>>,
        idle_timeout: Duration,
        native_telemetry: Option<ConnectionEventTelemetry>,
        origin: Option<String>,
    ) -> Self {
        metrics.connection_opened();
        if let Some(origin_metrics) = &origin_metrics {
            origin_metrics.connection_opened();
        }

        Self {
            inner: Arc::new(ConnectionTelemetryInner {
                metrics,
                origin_metrics,
                observed_uses: AtomicUsize::new(0),
                idle_since: Mutex::new(None),
                idle_timeout,
                closed: AtomicBool::new(false),
                aborted: AtomicBool::new(false),
                io_waker: Mutex::new(None),
                write_timeout: Mutex::new(WriteTimeoutState::default()),
                native_telemetry,
                origin,
            }),
        }
    }

    #[cfg(test)]
    pub(crate) fn request_started(
        &self,
        request_telemetry: Option<RequestTelemetry>,
        write_timeout: Option<RequestWriteTimeoutContext>,
    ) -> ConnectionUseGuard {
        self.request_started_with_body_completion(request_telemetry, write_timeout, None)
    }

    pub(crate) fn request_started_with_body_completion(
        &self,
        request_telemetry: Option<RequestTelemetry>,
        write_timeout: Option<RequestWriteTimeoutContext>,
        request_body_completion: Option<RequestBodyCompletion>,
    ) -> ConnectionUseGuard {
        let previous_uses = {
            let mut idle_since = self.lock_idle_since();
            let _ = self.leave_idle_locked(&mut idle_since);
            self.inner.observed_uses.fetch_add(1, Ordering::AcqRel)
        };
        let reused = previous_uses > 0;
        if reused {
            self.inner.metrics.connection_reused();
            if let Some(origin_metrics) = &self.inner.origin_metrics {
                origin_metrics.connection_reused();
            }
        }

        let request_connection_use = request_telemetry
            .as_ref()
            .zip(self.inner.origin.as_deref())
            .and_then(|(telemetry, origin)| telemetry.begin_connection_use(origin, reused));
        self.begin_request_write_timeout(
            previous_uses,
            write_timeout,
            request_telemetry.clone(),
            request_body_completion.clone(),
        );

        ConnectionUseGuard {
            telemetry: self.clone(),
            request_telemetry,
            request_connection_use,
            use_id: previous_uses,
            request_body_completion,
            write_timeout_finished: false,
            finished: false,
        }
    }

    pub(crate) fn is_same_connection(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.inner, &other.inner)
    }

    fn response_finished(
        &self,
        use_id: usize,
        outcome: ResponseBodyLifecycleOutcome,
        request_telemetry: Option<&RequestTelemetry>,
        request_connection_use: Option<&RequestConnectionUseTelemetry>,
    ) {
        match outcome {
            ResponseBodyLifecycleOutcome::ReuseEligible | ResponseBodyLifecycleOutcome::Closed => {
                if request_connection_use.is_some_and(|connection_use| !connection_use.finish()) {
                    let reason = if request_telemetry.is_some_and(RequestTelemetry::is_cancelled) {
                        ConnectionAbortReason::Cancelled
                    } else {
                        ConnectionAbortReason::Error(None)
                    };
                    self.abort_connection_use(
                        use_id,
                        request_telemetry,
                        request_connection_use,
                        reason,
                    );
                    return;
                }
                if outcome == ResponseBodyLifecycleOutcome::ReuseEligible {
                    self.enter_idle(use_id);
                }
            }
            ResponseBodyLifecycleOutcome::Aborted => {
                let reason = if request_telemetry.is_some_and(RequestTelemetry::is_cancelled) {
                    ConnectionAbortReason::Cancelled
                } else {
                    ConnectionAbortReason::Error(None)
                };
                self.abort_connection_use(
                    use_id,
                    request_telemetry,
                    request_connection_use,
                    reason,
                );
            }
        }
    }

    fn connection_closed(&self) {
        if self.inner.closed.swap(true, Ordering::AcqRel) {
            return;
        }
        self.clear_request_write_timeout();
        self.lock_io_waker().take();
        let mut idle_since = self.lock_idle_since();
        let idle_for = self.leave_idle_locked(&mut idle_since);

        self.inner.metrics.connection_closed();
        if let Some(origin_metrics) = &self.inner.origin_metrics {
            origin_metrics.connection_closed();
        }
        if let Some(native_telemetry) = &self.inner.native_telemetry {
            native_telemetry.closed();
        }
        if idle_for.is_some_and(|elapsed| elapsed >= self.inner.idle_timeout) {
            self.inner.metrics.idle_timeout_eviction();
            if let Some(origin_metrics) = &self.inner.origin_metrics {
                origin_metrics.idle_timeout_eviction();
            }
        }
    }

    fn enter_idle(&self, use_id: usize) {
        let mut idle_since = self.lock_idle_since();
        if self.inner.closed.load(Ordering::Acquire)
            || self.inner.aborted.load(Ordering::Acquire)
            || !self.is_current_use(use_id)
        {
            return;
        }
        if idle_since.is_some() {
            return;
        }

        *idle_since = Some(Instant::now());
        self.inner.metrics.connection_became_idle();
        if let Some(origin_metrics) = &self.inner.origin_metrics {
            origin_metrics.connection_became_idle();
        }
    }

    fn leave_idle_locked(&self, idle_since: &mut Option<Instant>) -> Option<Duration> {
        let idle_for = idle_since.take().map(|idle_since| idle_since.elapsed())?;
        self.inner.metrics.connection_left_idle();
        if let Some(origin_metrics) = &self.inner.origin_metrics {
            origin_metrics.connection_left_idle();
        }
        Some(idle_for)
    }

    fn abort(&self, request_telemetry: Option<&RequestTelemetry>, reason: ConnectionAbortReason) {
        self.clear_request_write_timeout();
        self.abort_current_connection_use(request_telemetry, None, reason);
    }

    fn begin_request_write_timeout(
        &self,
        use_id: usize,
        context: Option<RequestWriteTimeoutContext>,
        request_telemetry: Option<RequestTelemetry>,
        request_body_completion: Option<RequestBodyCompletion>,
    ) {
        let mut state = self.lock_write_timeout();
        if self.inner.closed.load(Ordering::Acquire) || self.inner.aborted.load(Ordering::Acquire) {
            return;
        }
        let previous_incomplete = state
            .active
            .as_ref()
            .and_then(|active| active.request_body_completion.as_ref())
            .is_some_and(|completion| !completion.is_complete());
        if previous_incomplete {
            let previous_request_telemetry = state
                .active
                .as_ref()
                .and_then(|active| active.request_telemetry.clone());
            drop(state);
            self.abort_current_connection_use(
                previous_request_telemetry.as_ref(),
                None,
                ConnectionAbortReason::Closed,
            );
            return;
        }
        let waker =
            state.begin_request(use_id, context, request_telemetry, request_body_completion);
        drop(state);
        let io_waker = self.lock_io_waker().clone();
        if let Some(waker) = waker.as_ref() {
            waker.wake_by_ref();
        }
        if let Some(io_waker) = io_waker {
            if waker
                .as_ref()
                .is_none_or(|waker| !waker.will_wake(&io_waker))
            {
                io_waker.wake();
            }
        }
    }

    fn finish_request_write_timeout(&self, use_id: usize) {
        let waker = self.lock_write_timeout().finish_request(use_id);
        if let Some(waker) = waker {
            waker.wake();
        }
    }

    fn clear_request_write_timeout(&self) {
        let waker = self.lock_write_timeout().clear_request();
        if let Some(waker) = waker {
            waker.wake();
        }
    }

    fn reset_write_timeout_progress(&self) {
        self.lock_write_timeout().reset_progress();
    }

    fn request_transport_flushed(&self) {
        let waker = self.lock_write_timeout().transport_flushed();
        if let Some(waker) = waker {
            waker.wake();
        }
    }

    fn poll_pending_write_timeout(
        &self,
        context: &mut Context<'_>,
    ) -> Poll<(Error, Option<RequestTelemetry>)> {
        self.lock_write_timeout().poll_pending(context)
    }

    fn poll_request_write_ready(&self, context: &mut Context<'_>) -> Poll<()> {
        self.lock_write_timeout().poll_request_ready(context)
    }

    fn abort_connection_use(
        &self,
        use_id: usize,
        request_telemetry: Option<&RequestTelemetry>,
        request_connection_use: Option<&RequestConnectionUseTelemetry>,
        reason: ConnectionAbortReason,
    ) {
        let mut idle_since = self.lock_idle_since();
        if !self.is_current_use(use_id) {
            drop(idle_since);
            if let Some(connection_use) = request_connection_use {
                connection_use.abort(reason.outcome(), reason.error_type());
            } else if let Some(request_telemetry) = request_telemetry {
                request_telemetry
                    .abort_active_connection_use(reason.outcome(), reason.error_type());
            }
            return;
        }
        self.abort_current_connection_use_locked(
            &mut idle_since,
            request_telemetry,
            request_connection_use,
            reason,
        );
    }

    fn abort_incomplete_connection_use(
        &self,
        request_telemetry: Option<&RequestTelemetry>,
        request_connection_use: Option<&RequestConnectionUseTelemetry>,
        reason: ConnectionAbortReason,
    ) {
        // Incomplete HTTP framing invalidates the physical socket even if the pool
        // has already assigned a newer logical use.
        self.abort_current_connection_use(request_telemetry, request_connection_use, reason);
    }

    fn abort_current_connection_use(
        &self,
        request_telemetry: Option<&RequestTelemetry>,
        request_connection_use: Option<&RequestConnectionUseTelemetry>,
        reason: ConnectionAbortReason,
    ) {
        let mut idle_since = self.lock_idle_since();
        self.abort_current_connection_use_locked(
            &mut idle_since,
            request_telemetry,
            request_connection_use,
            reason,
        );
    }

    fn abort_current_connection_use_locked(
        &self,
        idle_since: &mut Option<Instant>,
        request_telemetry: Option<&RequestTelemetry>,
        request_connection_use: Option<&RequestConnectionUseTelemetry>,
        reason: ConnectionAbortReason,
    ) {
        if self.inner.aborted.swap(true, Ordering::AcqRel) {
            if let Some(connection_use) = request_connection_use {
                connection_use.abort(reason.outcome(), reason.error_type());
            } else if let Some(request_telemetry) = request_telemetry {
                request_telemetry
                    .abort_active_connection_use(reason.outcome(), reason.error_type());
            }
            return;
        }
        let _ = self.leave_idle_locked(idle_since);
        let io_waker = self.lock_io_waker().take();

        self.inner.metrics.connection_aborted();
        if let Some(origin_metrics) = &self.inner.origin_metrics {
            origin_metrics.connection_aborted();
        }
        if let Some(connection_use) = request_connection_use {
            connection_use.abort(reason.outcome(), reason.error_type());
        } else if let (Some(request_telemetry), Some(origin)) =
            (request_telemetry, &self.inner.origin)
        {
            if !request_telemetry.abort_active_connection_use(reason.outcome(), reason.error_type())
                && !request_telemetry.is_cancelled()
            {
                request_telemetry.connection_aborted(
                    origin,
                    request_telemetry.current_redirect_hop(),
                    reason.outcome(),
                    reason.error_type(),
                );
            }
        }
        if let Some(io_waker) = io_waker {
            io_waker.wake();
        }
    }

    fn is_current_use(&self, use_id: usize) -> bool {
        self.inner.observed_uses.load(Ordering::Acquire) == use_id.wrapping_add(1)
    }

    fn lock_idle_since(&self) -> MutexGuard<'_, Option<Instant>> {
        self.inner
            .idle_since
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }

    fn lock_write_timeout(&self) -> MutexGuard<'_, WriteTimeoutState> {
        self.inner
            .write_timeout
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }

    fn lock_io_waker(&self) -> MutexGuard<'_, Option<Waker>> {
        self.inner
            .io_waker
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }

    fn prepare_io_poll(&self, context: &Context<'_>) -> Result<(), Error> {
        let mut io_waker = self.lock_io_waker();
        if self.inner.aborted.load(Ordering::Acquire) {
            return Err(connection_aborted_error());
        }
        if io_waker
            .as_ref()
            .is_none_or(|io_waker| !io_waker.will_wake(context.waker()))
        {
            *io_waker = Some(context.waker().clone());
        }
        Ok(())
    }
}

fn connection_aborted_error() -> Error {
    Error::new(ErrorKind::ConnectionAborted, "connection use aborted")
}

fn connection_open_error_type(error: &(dyn std::error::Error + 'static)) -> TelemetryErrorType {
    let mut current = Some(error);
    while let Some(error) = current {
        if error.downcast_ref::<SsrfViolation>().is_some() {
            return TelemetryErrorType::SsrfError;
        }
        current = error.source();
    }
    TelemetryErrorType::NetworkError
}

impl WriteTimeoutState {
    fn begin_request(
        &mut self,
        use_id: usize,
        context: Option<RequestWriteTimeoutContext>,
        request_telemetry: Option<RequestTelemetry>,
        request_body_completion: Option<RequestBodyCompletion>,
    ) -> Option<Waker> {
        let pending_waker = self.pending_waker.take();
        self.reset_progress();
        self.active = Some(ActiveRequestWriteTimeout {
            use_id,
            context,
            request_telemetry,
            request_body_completion,
        });
        pending_waker
    }

    fn finish_request(&mut self, use_id: usize) -> Option<Waker> {
        if self
            .active
            .as_ref()
            .is_none_or(|active| active.use_id != use_id)
        {
            return None;
        }
        self.active = None;
        let pending_waker = self.pending_waker.take();
        self.reset_progress();
        pending_waker
    }

    fn clear_request(&mut self) -> Option<Waker> {
        self.active = None;
        let pending_waker = self.pending_waker.take();
        self.reset_progress();
        pending_waker
    }

    fn reset_progress(&mut self) {
        self.pending_since = None;
        self.sleep = None;
        self.pending_waker = None;
    }

    fn transport_flushed(&mut self) -> Option<Waker> {
        let request_complete = self
            .active
            .as_ref()
            .and_then(|active| active.request_body_completion.as_ref())
            .is_some_and(|completion| {
                completion.mark_transport_flushed();
                completion.is_complete()
            });
        if request_complete {
            self.active = None;
        }
        let pending_waker = self.pending_waker.take();
        self.reset_progress();
        pending_waker
    }

    fn poll_request_ready(&mut self, context: &mut Context<'_>) -> Poll<()> {
        let completed_request = self
            .active
            .as_ref()
            .and_then(|active| active.request_body_completion.as_ref())
            .is_some_and(RequestBodyCompletion::is_complete);
        if completed_request {
            self.active = None;
            self.reset_progress();
        }
        let incomplete_wire_finished = self
            .active
            .as_ref()
            .and_then(|active| active.request_body_completion.as_ref())
            .is_some_and(RequestBodyCompletion::is_wire_finished);
        if incomplete_wire_finished {
            self.pending_since.get_or_insert_with(Instant::now);
            self.update_pending_waker(context.waker());
            return Poll::Pending;
        }
        if self.active.is_some() {
            return Poll::Ready(());
        }
        self.pending_since.get_or_insert_with(Instant::now);
        self.update_pending_waker(context.waker());
        Poll::Pending
    }

    fn poll_pending(
        &mut self,
        context: &mut Context<'_>,
    ) -> Poll<(Error, Option<RequestTelemetry>)> {
        let pending_since = *self.pending_since.get_or_insert_with(Instant::now);
        let Some(active) = self.active.as_ref() else {
            self.update_pending_waker(context.waker());
            return Poll::Pending;
        };
        let Some(timeout_context) = active.context.clone() else {
            self.update_pending_waker(context.waker());
            return Poll::Pending;
        };
        let request_telemetry = active.request_telemetry.clone();
        let request_body_completion = active.request_body_completion.clone();
        let sleep = self.sleep.get_or_insert_with(|| {
            let remaining = timeout_context
                .timeout()
                .saturating_sub(pending_since.elapsed());
            Box::pin(tokio::time::sleep(remaining))
        });

        if sleep.as_mut().poll(context).is_pending() {
            return Poll::Pending;
        }

        let timeout_error = timeout_context.timeout_error(pending_since);
        if let Some(request_body_completion) = request_body_completion {
            request_body_completion.mark_write_timeout(timeout_error.clone());
        }
        self.reset_progress();
        Poll::Ready((
            Error::new(ErrorKind::TimedOut, timeout_error),
            request_telemetry,
        ))
    }

    fn update_pending_waker(&mut self, waker: &Waker) {
        if self
            .pending_waker
            .as_ref()
            .is_none_or(|pending_waker| !pending_waker.will_wake(waker))
        {
            self.pending_waker = Some(waker.clone());
        }
    }
}

impl<T> InstrumentedConnection<T> {
    fn poll_pending_write_timeout(&mut self, context: &mut Context<'_>) -> Poll<Error> {
        match self.telemetry.poll_pending_write_timeout(context) {
            Poll::Ready((error, request_telemetry)) => {
                self.telemetry.abort(
                    request_telemetry.as_ref(),
                    ConnectionAbortReason::Error(Some(TelemetryErrorType::WriteTimeout)),
                );
                Poll::Ready(error)
            }
            Poll::Pending => Poll::Pending,
        }
    }
}

impl ConnectionUseGuard {
    pub(crate) fn request_body_completion(&self) -> Option<RequestBodyCompletion> {
        self.request_body_completion.clone()
    }

    pub(crate) fn request_write_timeout(&self) -> Option<RequestWriteTimeout> {
        self.request_body_completion
            .as_ref()
            .and_then(RequestBodyCompletion::write_timeout)
    }

    fn incomplete_upload(&self) -> bool {
        self.request_body_completion
            .as_ref()
            .is_some_and(|completion| !completion.is_complete())
    }

    fn abort_incomplete_upload(&self, reason: ConnectionAbortReason) {
        self.telemetry.abort_incomplete_connection_use(
            self.request_telemetry.as_ref(),
            self.request_connection_use.as_ref(),
            reason,
        );
    }

    fn request_write_finished(&mut self) {
        if !self.write_timeout_finished {
            self.telemetry.finish_request_write_timeout(self.use_id);
            self.write_timeout_finished = true;
        }
    }

    pub(crate) fn finish(mut self, outcome: ResponseBodyLifecycleOutcome) {
        if self.incomplete_upload() {
            self.abort_incomplete_upload(ConnectionAbortReason::Closed);
            self.request_write_finished();
        } else {
            self.request_write_finished();
            self.telemetry.response_finished(
                self.use_id,
                outcome,
                self.request_telemetry.as_ref(),
                self.request_connection_use.as_ref(),
            );
        }
        self.finished = true;
    }

    pub(crate) fn abort(mut self, reason: ConnectionAbortReason) {
        if self.incomplete_upload() {
            self.abort_incomplete_upload(reason);
        } else {
            self.telemetry.abort_connection_use(
                self.use_id,
                self.request_telemetry.as_ref(),
                self.request_connection_use.as_ref(),
                reason,
            );
        }
        self.request_write_finished();
        self.finished = true;
    }

    pub(crate) fn superseded(mut self) {
        self.request_write_finished();
        // Hyper can replace an unstarted stale-pool assignment with a fresh connection.
        self.telemetry.response_finished(
            self.use_id,
            ResponseBodyLifecycleOutcome::Closed,
            self.request_telemetry.as_ref(),
            self.request_connection_use.as_ref(),
        );
        self.finished = true;
    }
}

impl Drop for ConnectionUseGuard {
    fn drop(&mut self) {
        if !self.finished {
            if self.incomplete_upload() {
                let reason = if self
                    .request_telemetry
                    .as_ref()
                    .is_some_and(RequestTelemetry::is_cancelled)
                {
                    ConnectionAbortReason::Cancelled
                } else {
                    ConnectionAbortReason::Error(None)
                };
                self.abort_incomplete_upload(reason);
            } else {
                self.telemetry.response_finished(
                    self.use_id,
                    ResponseBodyLifecycleOutcome::Aborted,
                    self.request_telemetry.as_ref(),
                    self.request_connection_use.as_ref(),
                );
            }
            self.request_write_finished();
        }
    }
}

impl ConnectionAbortReason {
    fn outcome(self) -> TelemetryOutcome {
        match self {
            Self::Closed => TelemetryOutcome::Closed,
            Self::Cancelled => TelemetryOutcome::Cancelled,
            Self::Error(_) => TelemetryOutcome::Error,
        }
    }

    fn error_type(self) -> Option<TelemetryErrorType> {
        match self {
            Self::Closed => None,
            Self::Cancelled => Some(TelemetryErrorType::CancelledError),
            Self::Error(error_type) => error_type,
        }
    }
}

impl<T> Connection for InstrumentedConnection<T>
where
    T: Connection,
{
    fn connected(&self) -> Connected {
        self.inner.connected().extra(self.telemetry.clone())
    }
}

impl<T> Read for InstrumentedConnection<T>
where
    T: Read + Unpin,
{
    fn poll_read(
        self: Pin<&mut Self>,
        context: &mut Context<'_>,
        buffer: ReadBufCursor<'_>,
    ) -> Poll<Result<(), Error>> {
        let connection = self.get_mut();
        if let Err(error) = connection.telemetry.prepare_io_poll(context) {
            return Poll::Ready(Err(error));
        }
        Pin::new(&mut connection.inner).poll_read(context, buffer)
    }
}

impl<T> Write for InstrumentedConnection<T>
where
    T: Write + Unpin,
{
    fn poll_write(
        self: Pin<&mut Self>,
        context: &mut Context<'_>,
        buffer: &[u8],
    ) -> Poll<Result<usize, Error>> {
        let connection = self.get_mut();
        if let Err(error) = connection.telemetry.prepare_io_poll(context) {
            return Poll::Ready(Err(error));
        }
        if connection
            .telemetry
            .poll_request_write_ready(context)
            .is_pending()
        {
            return Poll::Pending;
        }
        match Pin::new(&mut connection.inner).poll_write(context, buffer) {
            Poll::Ready(Ok(written)) => {
                if written > 0 {
                    connection.telemetry.reset_write_timeout_progress();
                }
                Poll::Ready(Ok(written))
            }
            Poll::Ready(Err(error)) => Poll::Ready(Err(error)),
            Poll::Pending => match connection.poll_pending_write_timeout(context) {
                Poll::Ready(error) => Poll::Ready(Err(error)),
                Poll::Pending => Poll::Pending,
            },
        }
    }

    fn poll_flush(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Result<(), Error>> {
        let connection = self.get_mut();
        if let Err(error) = connection.telemetry.prepare_io_poll(context) {
            return Poll::Ready(Err(error));
        }
        if connection
            .telemetry
            .poll_request_write_ready(context)
            .is_pending()
        {
            return Poll::Pending;
        }
        match Pin::new(&mut connection.inner).poll_flush(context) {
            Poll::Ready(result) => {
                if result.is_ok() {
                    connection.telemetry.request_transport_flushed();
                }
                Poll::Ready(result)
            }
            Poll::Pending => match connection.poll_pending_write_timeout(context) {
                Poll::Ready(error) => Poll::Ready(Err(error)),
                Poll::Pending => Poll::Pending,
            },
        }
    }

    fn poll_shutdown(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Result<(), Error>> {
        let connection = self.get_mut();
        if let Err(error) = connection.telemetry.prepare_io_poll(context) {
            return Poll::Ready(Err(error));
        }
        Pin::new(&mut connection.inner).poll_shutdown(context)
    }

    fn is_write_vectored(&self) -> bool {
        self.inner.is_write_vectored()
    }

    fn poll_write_vectored(
        self: Pin<&mut Self>,
        context: &mut Context<'_>,
        buffers: &[IoSlice<'_>],
    ) -> Poll<Result<usize, Error>> {
        let connection = self.get_mut();
        if let Err(error) = connection.telemetry.prepare_io_poll(context) {
            return Poll::Ready(Err(error));
        }
        if connection
            .telemetry
            .poll_request_write_ready(context)
            .is_pending()
        {
            return Poll::Pending;
        }
        match Pin::new(&mut connection.inner).poll_write_vectored(context, buffers) {
            Poll::Ready(Ok(written)) => {
                if written > 0 {
                    connection.telemetry.reset_write_timeout_progress();
                }
                Poll::Ready(Ok(written))
            }
            Poll::Ready(Err(error)) => Poll::Ready(Err(error)),
            Poll::Pending => match connection.poll_pending_write_timeout(context) {
                Poll::Ready(error) => Poll::Ready(Err(error)),
                Poll::Pending => Poll::Pending,
            },
        }
    }
}

impl<T> Drop for InstrumentedConnection<T> {
    fn drop(&mut self) {
        self.telemetry.connection_closed();
    }
}

fn origin_from_uri(uri: &Uri) -> Option<String> {
    HttpUrl::parse(&uri.to_string())
        .ok()
        .map(|url| url.origin())
}
