#[cfg(test)]
mod tests;

use hyper::rt::{Read, ReadBufCursor, Write};
use hyper::Uri;
use hyper_util::client::legacy::connect::{Connected, Connection};
use std::future::Future;
use std::io::{Error, IoSlice};
use std::pin::Pin;
use std::task::{Context, Poll};
use tower_service::Service;

#[derive(Clone)]
pub(crate) struct HttpProxyConnector<C> {
    inner: C,
    http_proxy: Option<Uri>,
}

pub(crate) struct HttpProxyConnection<T> {
    inner: T,
    proxied: bool,
}

impl<C> HttpProxyConnector<C> {
    pub(crate) fn direct(inner: C) -> Self {
        Self {
            inner,
            http_proxy: None,
        }
    }

    pub(crate) fn http_proxy(inner: C, proxy_uri: Uri) -> Self {
        Self {
            inner,
            http_proxy: Some(proxy_uri),
        }
    }
}

impl<C> Service<Uri> for HttpProxyConnector<C>
where
    C: Service<Uri>,
    C::Response: Read + Write + Connection + Unpin + Send + 'static,
    C::Future: Send + 'static,
{
    type Response = HttpProxyConnection<C::Response>;
    type Error = C::Error;
    type Future = Pin<Box<dyn Future<Output = Result<Self::Response, Self::Error>> + Send>>;

    fn poll_ready(&mut self, context: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.inner.poll_ready(context)
    }

    fn call(&mut self, uri: Uri) -> Self::Future {
        let (connection_uri, proxied) = match &self.http_proxy {
            Some(proxy_uri) if uri.scheme_str() == Some("http") => (proxy_uri.clone(), true),
            _ => (uri, false),
        };
        let future = self.inner.call(connection_uri);

        Box::pin(async move {
            future
                .await
                .map(|inner| HttpProxyConnection { inner, proxied })
        })
    }
}

impl<T> Connection for HttpProxyConnection<T>
where
    T: Connection,
{
    fn connected(&self) -> Connected {
        if self.proxied {
            return self.inner.connected().proxy(true);
        }
        self.inner.connected()
    }
}

impl<T> Read for HttpProxyConnection<T>
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

impl<T> Write for HttpProxyConnection<T>
where
    T: Write + Unpin,
{
    fn poll_write(
        self: Pin<&mut Self>,
        context: &mut Context<'_>,
        buffer: &[u8],
    ) -> Poll<Result<usize, Error>> {
        Pin::new(&mut self.get_mut().inner).poll_write(context, buffer)
    }

    fn poll_flush(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Result<(), Error>> {
        Pin::new(&mut self.get_mut().inner).poll_flush(context)
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
        Pin::new(&mut self.get_mut().inner).poll_write_vectored(context, buffers)
    }
}
