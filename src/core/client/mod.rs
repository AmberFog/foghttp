mod body;
mod connection_limit;
mod proxy;
mod ssrf;
mod telemetry;
mod write_timeout;

pub(crate) use body::{
    buffered_request_body, streaming_request_body, upload_body_channel, RequestBody,
    UploadBodyReceiver, UploadBodySendError, UploadBodySender,
};
pub(crate) use connection_limit::{
    connection_acquire_timeout_from_error, with_connection_limit_timeout, ConnectionGate,
    ConnectionLimitContext,
};
use proxy::parse_proxy_endpoint;
pub(crate) use proxy::{HttpProxyConnector, HttpsTunnelConnector, ProxyTunnelTarget};
pub(crate) use ssrf::SsrfResolver;
pub(crate) use telemetry::{ConnectionTelemetry, ConnectionUseGuard, InstrumentedConnector};
pub(crate) use write_timeout::{
    current_request_write_timeout, request_write_timeout_from_error, with_request_write_timeout,
    RequestTaskContextExecutor, RequestWriteTimeout, RequestWriteTimeoutContext,
};

use crate::core::metrics::Metrics;
use crate::core::numeric::duration_from_secs;
use crate::core::policy::SsrfPolicy;
use crate::core::tls::build_tls_config;
use hyper_rustls::{HttpsConnector, HttpsConnectorBuilder};
use hyper_util::client::legacy::connect::dns::GaiResolver;
use hyper_util::client::legacy::connect::HttpConnector;
use hyper_util::client::legacy::Client;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;

type BoxSendFuture = Pin<Box<dyn Future<Output = ()> + Send>>;
type NetworkConnector = HttpConnector<SsrfResolver<GaiResolver>>;
type BaseConnector = HttpsConnector<HttpsTunnelConnector<NetworkConnector>>;
pub type HyperClient =
    Client<InstrumentedConnector<HttpProxyConnector<BaseConnector>>, RequestBody>;

#[derive(Clone)]
pub struct ClientOptions {
    pub max_idle_connections_per_host: usize,
    pub idle_timeout: f64,
    pub keepalive: bool,
    pub connect_timeout: f64,
    pub ca_certificates: Vec<Vec<u8>>,
    pub trust_webpki_roots: bool,
    pub http_proxy_url: Option<String>,
    pub https_proxy_url: Option<String>,
    pub https_proxy_authorization: Option<String>,
    pub ssrf_policy: Option<Arc<SsrfPolicy>>,
}

pub fn build_client_with_connection_gate(
    options: &ClientOptions,
    metrics: Arc<Metrics>,
    connection_gate: ConnectionGate,
) -> Result<HyperClient, String> {
    build_client_with_executor(
        options,
        metrics,
        connection_gate,
        RequestTaskContextExecutor,
        true,
    )
}

pub fn build_write_timeout_client_with_connection_gate(
    options: &ClientOptions,
    metrics: Arc<Metrics>,
    connection_gate: ConnectionGate,
) -> Result<HyperClient, String> {
    build_client_with_executor(
        options,
        metrics,
        connection_gate,
        RequestTaskContextExecutor,
        false,
    )
}

fn build_client_with_executor<E>(
    options: &ClientOptions,
    metrics: Arc<Metrics>,
    connection_gate: ConnectionGate,
    executor: E,
    pool_idle_connections: bool,
) -> Result<HyperClient, String>
where
    E: hyper::rt::Executor<BoxSendFuture> + Send + Sync + Clone + 'static,
{
    let connect_timeout = duration_from_secs("Timeouts.connect", options.connect_timeout)?;
    let idle_timeout = duration_from_secs("Limits.idle_timeout", options.idle_timeout)?;

    let resolver = SsrfResolver::new(GaiResolver::new(), options.ssrf_policy.is_some());
    let mut http = HttpConnector::new_with_resolver(resolver);
    http.enforce_http(false);
    http.set_connect_timeout(Some(connect_timeout));

    let tunnel_connector = match &options.https_proxy_url {
        Some(proxy_url) => HttpsTunnelConnector::https_proxy(
            http,
            ProxyTunnelTarget::new(
                parse_proxy_endpoint(proxy_url)?,
                options.https_proxy_authorization.as_deref(),
                connect_timeout,
            )?,
        ),
        None => HttpsTunnelConnector::direct(http),
    };

    let tls_config = build_tls_config(&options.ca_certificates, options.trust_webpki_roots)?;
    let connector = HttpsConnectorBuilder::new()
        .with_tls_config(tls_config)
        .https_or_http()
        .enable_http1()
        .wrap_connector(tunnel_connector);
    let proxy_connector = match &options.http_proxy_url {
        Some(proxy_url) => {
            HttpProxyConnector::http_proxy(connector, parse_proxy_endpoint(proxy_url)?)
        }
        None => HttpProxyConnector::direct(connector),
    };
    let connector =
        InstrumentedConnector::new(proxy_connector, metrics, connection_gate, idle_timeout);

    let mut builder = Client::builder(executor);
    builder.pool_max_idle_per_host(if pool_idle_connections && options.keepalive {
        options.max_idle_connections_per_host
    } else {
        0
    });
    builder.pool_idle_timeout(idle_timeout);
    Ok(builder.build(connector))
}
