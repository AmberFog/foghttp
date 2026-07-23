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
mod tests {
    use super::{SsrfResolver, SsrfResolverError};
    use crate::core::policy::SsrfViolation;
    use hyper::Uri;
    use hyper_util::client::legacy::connect::dns::Name;
    use hyper_util::client::legacy::connect::HttpConnector;
    use std::collections::VecDeque;
    use std::convert::Infallible;
    use std::future::{ready, Ready};
    use std::net::SocketAddr;
    use std::str::FromStr;
    use std::sync::{Arc, Mutex};
    use std::task::{Context, Poll};
    use tower_service::Service;

    #[test]
    fn disabled_resolver_preserves_the_underlying_address_iterator() {
        let private = address("127.0.0.1:80");
        let mut resolver = SsrfResolver::new(ScriptedResolver::new(vec![vec![private]]), false);

        let addresses = resolve(&mut resolver).expect("disabled guard must delegate");

        assert_eq!(addresses, vec![private]);
    }

    #[test]
    fn enabled_resolver_returns_the_exact_validated_addresses() {
        let public_v4 = address("8.8.8.8:80");
        let public_v6 = address("[2606:4700:4700::1111]:80");
        let mut resolver = guarded(vec![vec![public_v4, public_v6]]);

        let addresses = resolve(&mut resolver).expect("public addresses must pass");

        assert_eq!(addresses, vec![public_v4, public_v6]);
    }

    #[test]
    fn each_dns_resolution_is_revalidated_against_rebinding() {
        let public = address("8.8.8.8:80");
        let private = address("127.0.0.1:80");
        let mut resolver = guarded(vec![vec![public], vec![private]]);

        let first = resolve(&mut resolver).expect("first public resolution must pass");
        let second = resolve(&mut resolver);

        assert_eq!(first, vec![public]);
        assert!(matches!(second, Err(SsrfResolverError::Violation(_))));
    }

    #[test]
    fn http_connector_rejects_a_private_answer_after_a_public_resolution() {
        let public = address("8.8.8.8:80");
        let private = address("127.0.0.1:80");
        let mut resolver = guarded(vec![vec![public], vec![private]]);
        let first = resolve(&mut resolver).expect("first public resolution must pass");
        let mut connector = HttpConnector::new_with_resolver(resolver);

        let error = tokio::runtime::Builder::new_current_thread()
            .build()
            .expect("test runtime")
            .block_on(connector.call(Uri::from_static("http://example.test/")))
            .expect_err("rebound private answer must fail before TCP connect");

        assert_eq!(first, vec![public]);
        assert!(error_chain_contains_ssrf_violation(&error));
    }

    #[test]
    fn one_blocked_dns_answer_rejects_the_entire_resolution() {
        let public = address("8.8.8.8:80");
        let private = address("127.0.0.1:80");
        let mut resolver = guarded(vec![vec![public, private]]);

        let result = resolve(&mut resolver);

        assert!(matches!(result, Err(SsrfResolverError::Violation(_))));
    }

    fn guarded(responses: Vec<Vec<SocketAddr>>) -> SsrfResolver<ScriptedResolver> {
        SsrfResolver::new(ScriptedResolver::new(responses), true)
    }

    fn resolve(
        resolver: &mut SsrfResolver<ScriptedResolver>,
    ) -> Result<Vec<SocketAddr>, SsrfResolverError<Infallible>> {
        tokio::runtime::Builder::new_current_thread()
            .build()
            .expect("test runtime")
            .block_on(resolver.call(name()))
            .map(Iterator::collect)
    }

    fn name() -> Name {
        Name::from_str("example.test").expect("valid name")
    }

    fn address(value: &str) -> SocketAddr {
        value.parse().expect("valid socket address")
    }

    fn error_chain_contains_ssrf_violation(mut error: &(dyn std::error::Error + 'static)) -> bool {
        loop {
            if error.downcast_ref::<SsrfViolation>().is_some() {
                return true;
            }
            let Some(source) = error.source() else {
                return false;
            };
            error = source;
        }
    }

    #[derive(Clone)]
    struct ScriptedResolver {
        responses: Arc<Mutex<VecDeque<Vec<SocketAddr>>>>,
    }

    impl ScriptedResolver {
        fn new(responses: Vec<Vec<SocketAddr>>) -> Self {
            Self {
                responses: Arc::new(Mutex::new(responses.into())),
            }
        }
    }

    impl Service<Name> for ScriptedResolver {
        type Response = std::vec::IntoIter<SocketAddr>;
        type Error = Infallible;
        type Future = Ready<Result<Self::Response, Self::Error>>;

        fn poll_ready(&mut self, _context: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
            Poll::Ready(Ok(()))
        }

        fn call(&mut self, _name: Name) -> Self::Future {
            let response = self
                .responses
                .lock()
                .expect("resolver script lock")
                .pop_front()
                .expect("scripted resolution");
            ready(Ok(response.into_iter()))
        }
    }
}
