mod proxy;
mod telemetry;

pub(crate) use proxy::{HttpProxyConnector, HttpsTunnelConnector, ProxyTunnelTarget};
pub(crate) use telemetry::{ConnectionTelemetry, ConnectionUseGuard, InstrumentedConnector};

use crate::core::metrics::Metrics;
use crate::core::numeric::duration_from_secs;
use crate::core::tls::build_tls_config;
use bytes::Bytes;
use http_body_util::Full;
use hyper_rustls::{HttpsConnector, HttpsConnectorBuilder};
use hyper_util::client::legacy::connect::HttpConnector;
use hyper_util::client::legacy::Client;
use hyper_util::rt::TokioExecutor;
use std::str::FromStr;
use std::sync::Arc;

pub type RequestBody = Full<Bytes>;
type BaseConnector = HttpsConnector<HttpsTunnelConnector<HttpConnector>>;
pub type HyperClient =
    Client<InstrumentedConnector<HttpProxyConnector<BaseConnector>>, RequestBody>;

#[derive(Clone, Debug)]
pub struct ClientOptions {
    pub max_idle_connections_per_host: usize,
    pub idle_timeout: f64,
    pub keepalive: bool,
    pub connect_timeout: f64,
    pub ca_certificates: Vec<Vec<u8>>,
    pub trust_webpki_roots: bool,
    // Proxy endpoints are kept per scheme: `http_proxy_url` serves plain-HTTP
    // targets in absolute-form, `https_proxy_url` tunnels HTTPS targets via
    // CONNECT. They may point at the same or different proxies.
    pub http_proxy_url: Option<String>,
    pub https_proxy_url: Option<String>,
    pub https_proxy_authorization: Option<String>,
}

pub fn build_client(options: &ClientOptions, metrics: Arc<Metrics>) -> Result<HyperClient, String> {
    let connect_timeout = duration_from_secs("Timeouts.connect", options.connect_timeout)?;

    let mut http = HttpConnector::new();
    http.enforce_http(false);
    http.set_connect_timeout(Some(connect_timeout));

    // Below TLS: HTTPS targets tunnel through the https-scheme proxy via CONNECT.
    let tunnel = match &options.https_proxy_url {
        Some(proxy_url) => HttpsTunnelConnector::https_proxy(
            http,
            ProxyTunnelTarget::new(
                hyper::Uri::from_str(proxy_url).map_err(|err| err.to_string())?,
                options.https_proxy_authorization.clone(),
                connect_timeout,
            ),
        ),
        None => HttpsTunnelConnector::direct(http),
    };

    let tls_config = build_tls_config(&options.ca_certificates, options.trust_webpki_roots)?;
    let connector = HttpsConnectorBuilder::new()
        .with_tls_config(tls_config)
        .https_or_http()
        .enable_http1()
        .wrap_connector(tunnel);
    // Above TLS: plain-HTTP targets route to the http-scheme proxy in absolute-form.
    let connector = match &options.http_proxy_url {
        Some(proxy_url) => HttpProxyConnector::http_proxy(
            connector,
            hyper::Uri::from_str(proxy_url).map_err(|err| err.to_string())?,
        ),
        None => HttpProxyConnector::direct(connector),
    };
    let connector = InstrumentedConnector::new(connector, metrics);

    let mut builder = Client::builder(TokioExecutor::new());
    builder.pool_max_idle_per_host(if options.keepalive {
        options.max_idle_connections_per_host
    } else {
        0
    });
    builder.pool_idle_timeout(duration_from_secs(
        "Limits.idle_timeout",
        options.idle_timeout,
    )?);
    Ok(builder.build(connector))
}
