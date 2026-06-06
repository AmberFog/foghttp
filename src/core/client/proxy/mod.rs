#[cfg(test)]
mod tests;

use crate::messages::{
    proxy_connect_rejected, PROXY_CONNECT_CLOSED, PROXY_CONNECT_INVALID_RESPONSE,
    PROXY_CONNECT_TIMEOUT,
};
use hyper::rt::{Read, ReadBufCursor, Write};
use hyper::Uri;
use hyper_util::client::legacy::connect::{Connected, Connection};
use hyper_util::rt::TokioIo;
use std::future::Future;
use std::io::{Error, IoSlice};
use std::pin::Pin;
use std::task::{Context, Poll};
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tower_service::Service;

type BoxError = Box<dyn std::error::Error + Send + Sync>;

const MAX_CONNECT_RESPONSE_BYTES: usize = 8 * 1024;

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

/// Proxy endpoint used to establish an HTTPS `CONNECT` tunnel.
///
/// `authorization` is the transport-managed `Proxy-Authorization` header value
/// sent only on the CONNECT request to the proxy, never on the tunnelled
/// request to the target origin.
#[derive(Clone)]
pub(crate) struct ProxyTunnelTarget {
    uri: Uri,
    authorization: Option<String>,
    connect_timeout: Duration,
}

impl ProxyTunnelTarget {
    pub(crate) fn new(uri: Uri, authorization: Option<String>, connect_timeout: Duration) -> Self {
        Self {
            uri,
            authorization,
            connect_timeout,
        }
    }
}

/// Connector that tunnels `https` targets through an HTTP proxy via `CONNECT`.
///
/// It sits below the TLS layer: for `https` targets with a proxy configured it
/// connects to the proxy, performs the `CONNECT` handshake to the target
/// authority, and returns the raw tunnelled stream so the TLS layer validates
/// the certificate against the *target* host. All other targets (direct, or the
/// plain-HTTP absolute-form proxy path) pass straight through to the inner
/// connector unchanged.
#[derive(Clone)]
pub(crate) struct HttpsTunnelConnector<C> {
    inner: C,
    proxy: Option<ProxyTunnelTarget>,
}

impl<C> HttpsTunnelConnector<C> {
    pub(crate) fn direct(inner: C) -> Self {
        Self { inner, proxy: None }
    }

    pub(crate) fn https_proxy(inner: C, proxy: ProxyTunnelTarget) -> Self {
        Self {
            inner,
            proxy: Some(proxy),
        }
    }
}

impl<C> Service<Uri> for HttpsTunnelConnector<C>
where
    C: Service<Uri>,
    C::Response: Read + Write + Connection + Unpin + Send + 'static,
    C::Future: Send + 'static,
    C::Error: Into<BoxError>,
{
    type Response = C::Response;
    type Error = BoxError;
    type Future = Pin<Box<dyn Future<Output = Result<Self::Response, Self::Error>> + Send>>;

    fn poll_ready(&mut self, context: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.inner.poll_ready(context).map_err(Into::into)
    }

    fn call(&mut self, uri: Uri) -> Self::Future {
        match &self.proxy {
            Some(proxy) if uri.scheme_str() == Some("https") => {
                let authority = match tunnel_authority(&uri) {
                    Ok(authority) => authority,
                    Err(error) => return Box::pin(async move { Err(error) }),
                };
                let proxy_authorization = proxy.authorization.clone();
                let connect_timeout = proxy.connect_timeout;
                let connect = self.inner.call(proxy.uri.clone());
                Box::pin(async move {
                    // Bound the whole connect phase (TCP connect to the proxy plus
                    // the CONNECT handshake) by the connect timeout so a proxy that
                    // accepts the socket but never answers CONNECT cannot hang the
                    // request until the outer total timeout fires.
                    let setup = async move {
                        let stream = connect.await.map_err(Into::into)?;
                        establish_tunnel(stream, &authority, proxy_authorization.as_deref()).await
                    };
                    match tokio::time::timeout(connect_timeout, setup).await {
                        Ok(result) => result,
                        Err(_elapsed) => Err(PROXY_CONNECT_TIMEOUT.into()),
                    }
                })
            }
            _ => {
                let connect = self.inner.call(uri);
                Box::pin(async move { connect.await.map_err(Into::into) })
            }
        }
    }
}

fn tunnel_authority(uri: &Uri) -> Result<String, BoxError> {
    let authority = uri
        .authority()
        .ok_or_else(|| BoxError::from("proxied request target is missing an authority"))?;
    let port = authority.port_u16().unwrap_or(443);
    Ok(format!("{}:{}", authority.host(), port))
}

async fn establish_tunnel<T>(
    stream: T,
    authority: &str,
    proxy_authorization: Option<&str>,
) -> Result<T, BoxError>
where
    T: Read + Write + Unpin,
{
    let mut io = TokioIo::new(stream);
    let mut request = format!("CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n");
    if let Some(authorization) = proxy_authorization {
        request.push_str("Proxy-Authorization: ");
        request.push_str(authorization);
        request.push_str("\r\n");
    }
    request.push_str("\r\n");
    io.write_all(request.as_bytes()).await?;
    io.flush().await?;

    let mut response = Vec::with_capacity(256);
    let mut chunk = [0_u8; 256];
    loop {
        let read = io.read(&mut chunk).await?;
        if read == 0 {
            return Err(PROXY_CONNECT_CLOSED.into());
        }
        response.extend_from_slice(&chunk[..read]);
        if let Some(headers_end) = find_headers_end(&response) {
            if response.len() != headers_end {
                return Err(PROXY_CONNECT_INVALID_RESPONSE.into());
            }
            let status = parse_connect_status(&response)?;
            if !(200..300).contains(&status) {
                return Err(proxy_connect_rejected(status).into());
            }
            return Ok(io.into_inner());
        }
        if response.len() > MAX_CONNECT_RESPONSE_BYTES {
            return Err(PROXY_CONNECT_INVALID_RESPONSE.into());
        }
    }
}

fn find_headers_end(buffer: &[u8]) -> Option<usize> {
    buffer
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .map(|index| index + 4)
}

fn parse_connect_status(response: &[u8]) -> Result<u16, BoxError> {
    let line_end = response
        .windows(2)
        .position(|window| window == b"\r\n")
        .ok_or_else(|| BoxError::from(PROXY_CONNECT_INVALID_RESPONSE))?;
    let status_line = std::str::from_utf8(&response[..line_end])
        .map_err(|_| BoxError::from(PROXY_CONNECT_INVALID_RESPONSE))?;
    let mut parts = status_line.split_whitespace();
    let version = parts.next().unwrap_or_default();
    if !version.starts_with("HTTP/1.") {
        return Err(PROXY_CONNECT_INVALID_RESPONSE.into());
    }
    parts
        .next()
        .and_then(|code| code.parse::<u16>().ok())
        .ok_or_else(|| BoxError::from(PROXY_CONNECT_INVALID_RESPONSE))
}
