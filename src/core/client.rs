use crate::core::numeric::duration_from_secs;
use crate::core::tls::build_tls_config;
use bytes::Bytes;
use http_body_util::Full;
use hyper_rustls::{HttpsConnector, HttpsConnectorBuilder};
use hyper_util::client::legacy::connect::HttpConnector;
use hyper_util::client::legacy::Client;
use hyper_util::rt::TokioExecutor;

pub type RequestBody = Full<Bytes>;
pub type HyperClient = Client<HttpsConnector<HttpConnector>, RequestBody>;

#[derive(Clone, Debug)]
pub struct ClientOptions {
    pub max_idle_connections_per_host: usize,
    pub idle_timeout: f64,
    pub keepalive: bool,
    pub connect_timeout: f64,
    pub ca_certificates: Vec<Vec<u8>>,
}

pub fn build_client(options: &ClientOptions) -> Result<HyperClient, String> {
    let mut http = HttpConnector::new();
    http.enforce_http(false);
    http.set_connect_timeout(Some(duration_from_secs(
        "Timeouts.connect",
        options.connect_timeout,
    )?));

    let tls_config = build_tls_config(&options.ca_certificates)?;
    let connector = HttpsConnectorBuilder::new()
        .with_tls_config(tls_config)
        .https_or_http()
        .enable_http1()
        .wrap_connector(http);

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
