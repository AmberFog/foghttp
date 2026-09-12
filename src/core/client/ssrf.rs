use crate::core::policy::{validate_resolved_address, SsrfViolation};
use hyper_util::client::legacy::connect::dns::Name;
use std::error::Error;
use std::fmt::{Debug, Display, Formatter};
use std::future::Future;
use std::net::SocketAddr;
use std::pin::Pin;
use std::task::{ready, Context, Poll};
use tower_service::Service;

#[derive(Clone)]
pub(crate) struct SsrfResolver<R> {
    inner: R,
    enabled: bool,
}

pub(crate) enum SsrfAddrs<A> {
    Unchecked(A),
    Checked(std::vec::IntoIter<SocketAddr>),
}

pub(crate) struct SsrfResolveFuture<F> {
    inner: F,
    checked_host: Option<String>,
}

#[derive(Debug)]
pub(crate) enum SsrfResolverError<E> {
    Dns(E),
    Violation(SsrfViolation),
}

impl<R> SsrfResolver<R> {
    pub(crate) fn new(inner: R, enabled: bool) -> Self {
        Self { inner, enabled }
    }
}

impl<R> Debug for SsrfResolver<R>
where
    R: Debug,
{
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("SsrfResolver")
            .field("inner", &self.inner)
            .field("enabled", &self.enabled)
            .finish()
    }
}

impl<R> Service<Name> for SsrfResolver<R>
where
    R: Service<Name>,
    R::Response: Iterator<Item = SocketAddr>,
    R::Future: Unpin,
{
    type Response = SsrfAddrs<R::Response>;
    type Error = SsrfResolverError<R::Error>;
    type Future = SsrfResolveFuture<R::Future>;

    fn poll_ready(&mut self, context: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.inner
            .poll_ready(context)
            .map_err(SsrfResolverError::Dns)
    }

    fn call(&mut self, name: Name) -> Self::Future {
        let checked_host = self.enabled.then(|| name.as_str().to_owned());
        SsrfResolveFuture {
            inner: self.inner.call(name),
            checked_host,
        }
    }
}

impl<F, A, E> Future for SsrfResolveFuture<F>
where
    F: Future<Output = Result<A, E>> + Unpin,
    A: Iterator<Item = SocketAddr>,
{
    type Output = Result<SsrfAddrs<A>, SsrfResolverError<E>>;

    fn poll(mut self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Self::Output> {
        let addresses =
            ready!(Pin::new(&mut self.inner).poll(context)).map_err(SsrfResolverError::Dns)?;
        let Some(host) = self.checked_host.take() else {
            return Poll::Ready(Ok(SsrfAddrs::Unchecked(addresses)));
        };
        let mut checked = Vec::new();
        for address in addresses {
            if let Err(error) = validate_resolved_address(&host, address.ip()) {
                return Poll::Ready(Err(SsrfResolverError::Violation(error)));
            }
            checked.push(address);
        }
        Poll::Ready(Ok(SsrfAddrs::Checked(checked.into_iter())))
    }
}

impl<A> Iterator for SsrfAddrs<A>
where
    A: Iterator<Item = SocketAddr>,
{
    type Item = SocketAddr;

    fn next(&mut self) -> Option<Self::Item> {
        match self {
            Self::Unchecked(addresses) => addresses.next(),
            Self::Checked(addresses) => addresses.next(),
        }
    }
}

impl<E> Display for SsrfResolverError<E>
where
    E: Display,
{
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Dns(error) => Display::fmt(error, formatter),
            Self::Violation(error) => Display::fmt(error, formatter),
        }
    }
}

impl<E> Error for SsrfResolverError<E>
where
    E: Error + 'static,
{
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Dns(error) => Some(error),
            Self::Violation(error) => Some(error),
        }
    }
}

#[cfg(test)]
mod tests;
