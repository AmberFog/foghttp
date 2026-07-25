#[cfg(test)]
mod tests;

use super::connection_limit::{ConnectionGate, ConnectionPermit};
use super::write_timeout::{current_request_write_timeout, RequestWriteTimeoutContext};
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
use std::task::{Context, Poll};
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
    write_timeout: WriteTimeoutState,
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
    native_telemetry: Option<ConnectionEventTelemetry>,
    origin: Option<String>,
}

#[derive(Default)]
struct WriteTimeoutState {
    pending_since: Option<Instant>,
    sleep: Option<Pin<Box<Sleep>>>,
    context: Option<RequestWriteTimeoutContext>,
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
                        write_timeout: WriteTimeoutState::default(),
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
                native_telemetry,
                origin,
            }),
        }
    }

    pub(crate) fn request_started(
        &self,
        request_telemetry: Option<RequestTelemetry>,
    ) -> ConnectionUseGuard {
        let _ = self.leave_idle();
        let previous_uses = self.inner.observed_uses.fetch_add(1, Ordering::Relaxed);
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

        ConnectionUseGuard {
            telemetry: self.clone(),
            request_telemetry,
            request_connection_use,
            finished: false,
        }
    }

    pub(crate) fn is_same_connection(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.inner, &other.inner)
    }

    fn response_finished(
        &self,
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
                    self.abort_connection_use(request_telemetry, request_connection_use, reason);
                    return;
                }
                if outcome == ResponseBodyLifecycleOutcome::ReuseEligible {
                    self.enter_idle();
                }
            }
            ResponseBodyLifecycleOutcome::Aborted => {
                let reason = if request_telemetry.is_some_and(RequestTelemetry::is_cancelled) {
                    ConnectionAbortReason::Cancelled
                } else {
                    ConnectionAbortReason::Error(None)
                };
                self.abort_connection_use(request_telemetry, request_connection_use, reason);
            }
        }
    }

    fn connection_closed(&self) {
        let mut idle_since = self.lock_idle_since();
        if self.inner.closed.swap(true, Ordering::AcqRel) {
            return;
        }
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

    fn enter_idle(&self) {
        let mut idle_since = self.lock_idle_since();
        if self.inner.closed.load(Ordering::Acquire) {
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

    fn leave_idle(&self) -> Option<Duration> {
        let mut idle_since = self.lock_idle_since();
        self.leave_idle_locked(&mut idle_since)
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
        self.abort_connection_use(request_telemetry, None, reason);
    }

    fn abort_connection_use(
        &self,
        request_telemetry: Option<&RequestTelemetry>,
        request_connection_use: Option<&RequestConnectionUseTelemetry>,
        reason: ConnectionAbortReason,
    ) {
        if self.inner.aborted.swap(true, Ordering::AcqRel) {
            if let Some(connection_use) = request_connection_use {
                connection_use.finish();
            }
            return;
        }

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
            {
                request_telemetry.connection_aborted(
                    origin,
                    request_telemetry.current_redirect_hop(),
                    reason.outcome(),
                    reason.error_type(),
                );
            }
        }
    }

    fn lock_idle_since(&self) -> MutexGuard<'_, Option<Instant>> {
        self.inner
            .idle_since
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
    }
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
    fn reset(&mut self) {
        self.pending_since = None;
        self.sleep = None;
        self.context = None;
    }

    fn poll_pending(&mut self, context: &mut Context<'_>) -> Poll<Error> {
        if self.context.is_none() {
            self.context = current_request_write_timeout();
            if self.context.is_none() {
                self.reset();
                return Poll::Pending;
            }
        }
        let timeout_context = self
            .context
            .as_ref()
            .expect("write timeout context is checked before polling timeout");
        let pending_since = *self.pending_since.get_or_insert_with(Instant::now);
        let sleep = self
            .sleep
            .get_or_insert_with(|| Box::pin(tokio::time::sleep(timeout_context.timeout())));

        if sleep.as_mut().poll(context).is_pending() {
            return Poll::Pending;
        }

        let timeout_error = timeout_context.timeout_error(pending_since);
        self.reset();
        Poll::Ready(Error::new(ErrorKind::TimedOut, timeout_error))
    }
}

impl<T> InstrumentedConnection<T> {
    fn poll_pending_write_timeout(&mut self, context: &mut Context<'_>) -> Poll<Error> {
        match self.write_timeout.poll_pending(context) {
            Poll::Ready(error) => {
                let request_telemetry = current_request_telemetry();
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
    pub(crate) fn finish(mut self, outcome: ResponseBodyLifecycleOutcome) {
        self.telemetry.response_finished(
            outcome,
            self.request_telemetry.as_ref(),
            self.request_connection_use.as_ref(),
        );
        self.finished = true;
    }

    pub(crate) fn abort(mut self, reason: ConnectionAbortReason) {
        self.telemetry.abort_connection_use(
            self.request_telemetry.as_ref(),
            self.request_connection_use.as_ref(),
            reason,
        );
        self.finished = true;
    }

    pub(crate) fn superseded(mut self) {
        // Hyper can replace an unstarted stale-pool assignment with a fresh connection.
        self.telemetry.response_finished(
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
            self.telemetry.response_finished(
                ResponseBodyLifecycleOutcome::Aborted,
                self.request_telemetry.as_ref(),
                self.request_connection_use.as_ref(),
            );
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
        Pin::new(&mut self.get_mut().inner).poll_read(context, buffer)
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
        match Pin::new(&mut connection.inner).poll_write(context, buffer) {
            Poll::Ready(result) => {
                connection.write_timeout.reset();
                Poll::Ready(result)
            }
            Poll::Pending => match connection.poll_pending_write_timeout(context) {
                Poll::Ready(error) => Poll::Ready(Err(error)),
                Poll::Pending => Poll::Pending,
            },
        }
    }

    fn poll_flush(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Result<(), Error>> {
        let connection = self.get_mut();
        match Pin::new(&mut connection.inner).poll_flush(context) {
            Poll::Ready(result) => {
                connection.write_timeout.reset();
                Poll::Ready(result)
            }
            Poll::Pending => match connection.poll_pending_write_timeout(context) {
                Poll::Ready(error) => Poll::Ready(Err(error)),
                Poll::Pending => Poll::Pending,
            },
        }
    }

    fn poll_shutdown(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Result<(), Error>> {
        Pin::new(&mut self.get_mut().inner).poll_shutdown(context)
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
        match Pin::new(&mut connection.inner).poll_write_vectored(context, buffers) {
            Poll::Ready(result) => {
                connection.write_timeout.reset();
                Poll::Ready(result)
            }
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
