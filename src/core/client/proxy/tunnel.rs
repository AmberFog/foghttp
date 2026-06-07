use super::authorization::ProxyAuthorization;
use crate::messages::{
    proxy_connect_rejected, PROXY_CONNECT_CLOSED, PROXY_CONNECT_INVALID_RESPONSE,
    PROXY_CONNECT_TIMEOUT,
};
use bytes::{Buf, Bytes};
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
pub(crate) struct ProxyTunnelTarget {
    uri: Uri,
    authorization: Option<ProxyAuthorization>,
    connect_timeout: Duration,
}

impl ProxyTunnelTarget {
    pub(crate) fn new(
        uri: Uri,
        authorization: Option<&str>,
        connect_timeout: Duration,
    ) -> Result<Self, String> {
        let authorization = authorization.map(ProxyAuthorization::parse).transpose()?;
        Ok(Self {
            uri,
            authorization,
            connect_timeout,
        })
    }
}

#[derive(Clone)]
pub(crate) struct HttpsTunnelConnector<C> {
    inner: C,
    proxy: Option<ProxyTunnelTarget>,
}

pub(crate) struct HttpsTunnelConnection<T> {
    inner: T,
    read_prefix: Option<Bytes>,
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
    type Response = HttpsTunnelConnection<C::Response>;
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
                    let connect_phase = async move {
                        let stream = connect.await.map_err(Into::into)?;
                        establish_tunnel(stream, &authority, proxy_authorization.as_ref()).await
                    };
                    match tokio::time::timeout(connect_timeout, connect_phase).await {
                        Ok(result) => result,
                        Err(_elapsed) => Err(PROXY_CONNECT_TIMEOUT.into()),
                    }
                })
            }
            _ => {
                let connect = self.inner.call(uri);
                Box::pin(async move {
                    connect
                        .await
                        .map(HttpsTunnelConnection::direct)
                        .map_err(Into::into)
                })
            }
        }
    }
}

impl<T> HttpsTunnelConnection<T> {
    fn direct(inner: T) -> Self {
        Self {
            inner,
            read_prefix: None,
        }
    }

    fn with_read_prefix(inner: T, read_prefix: Bytes) -> Self {
        Self {
            inner,
            read_prefix: Some(read_prefix),
        }
    }
}

impl<T> Connection for HttpsTunnelConnection<T>
where
    T: Connection,
{
    fn connected(&self) -> Connected {
        self.inner.connected()
    }
}

impl<T> Read for HttpsTunnelConnection<T>
where
    T: Read + Unpin,
{
    fn poll_read(
        mut self: Pin<&mut Self>,
        context: &mut Context<'_>,
        mut buffer: ReadBufCursor<'_>,
    ) -> Poll<Result<(), Error>> {
        if let Some(mut prefix) = self.read_prefix.take() {
            if !prefix.is_empty() {
                let copy_len = prefix.len().min(buffer.remaining());
                buffer.put_slice(&prefix[..copy_len]);
                prefix.advance(copy_len);
                if !prefix.is_empty() {
                    self.read_prefix = Some(prefix);
                }
                return Poll::Ready(Ok(()));
            }
        }
        Pin::new(&mut self.inner).poll_read(context, buffer)
    }
}

impl<T> Write for HttpsTunnelConnection<T>
where
    T: Write + Unpin,
{
    fn poll_write(
        mut self: Pin<&mut Self>,
        context: &mut Context<'_>,
        buffer: &[u8],
    ) -> Poll<Result<usize, Error>> {
        Pin::new(&mut self.inner).poll_write(context, buffer)
    }

    fn poll_flush(mut self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Result<(), Error>> {
        Pin::new(&mut self.inner).poll_flush(context)
    }

    fn poll_shutdown(
        mut self: Pin<&mut Self>,
        context: &mut Context<'_>,
    ) -> Poll<Result<(), Error>> {
        Pin::new(&mut self.inner).poll_shutdown(context)
    }

    fn is_write_vectored(&self) -> bool {
        self.inner.is_write_vectored()
    }

    fn poll_write_vectored(
        mut self: Pin<&mut Self>,
        context: &mut Context<'_>,
        buffers: &[IoSlice<'_>],
    ) -> Poll<Result<usize, Error>> {
        Pin::new(&mut self.inner).poll_write_vectored(context, buffers)
    }
}

pub(super) fn tunnel_authority(uri: &Uri) -> Result<String, BoxError> {
    let authority = uri
        .authority()
        .ok_or_else(|| BoxError::from("proxied request target is missing an authority"))?;
    let port = authority.port_u16().unwrap_or(443);
    Ok(format!("{}:{}", authority.host(), port))
}

pub(super) async fn establish_tunnel<T>(
    stream: T,
    authority: &str,
    proxy_authorization: Option<&ProxyAuthorization>,
) -> Result<HttpsTunnelConnection<T>, BoxError>
where
    T: Read + Write + Unpin,
{
    let mut io = TokioIo::new(stream);
    let mut request = format!("CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n");
    if let Some(authorization) = proxy_authorization {
        request.push_str("Proxy-Authorization: ");
        request.push_str(authorization.as_str());
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
            let status = parse_connect_status(&response[..headers_end])?;
            if !(200..300).contains(&status) {
                return Err(proxy_connect_rejected(status).into());
            }
            if response.len() == headers_end {
                return Ok(HttpsTunnelConnection::direct(io.into_inner()));
            }
            let read_prefix = Bytes::copy_from_slice(&response[headers_end..]);
            return Ok(HttpsTunnelConnection::with_read_prefix(
                io.into_inner(),
                read_prefix,
            ));
        }
        if response.len() > MAX_CONNECT_RESPONSE_BYTES {
            return Err(PROXY_CONNECT_INVALID_RESPONSE.into());
        }
    }
}

pub(super) fn find_headers_end(buffer: &[u8]) -> Option<usize> {
    buffer
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .map(|index| index + 4)
}

pub(super) fn parse_connect_status(response: &[u8]) -> Result<u16, BoxError> {
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
