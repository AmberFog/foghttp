use bytes::Bytes;
use http_body_util::Full;
use hyper_rustls::{HttpsConnector, HttpsConnectorBuilder};
use hyper_util::client::legacy::connect::HttpConnector;
use hyper_util::client::legacy::Client;
use hyper_util::rt::TokioExecutor;
use std::time::Duration;

pub type RequestBody = Full<Bytes>;
pub type HyperClient = Client<HttpsConnector<HttpConnector>, RequestBody>;

#[derive(Clone, Copy, Debug)]
pub struct ClientOptions {
    pub max_connections_per_host: usize,
    pub idle_timeout: f64,
    pub keepalive: bool,
    pub connect_timeout: f64,
}

pub fn build_client(options: ClientOptions) -> HyperClient {
    let mut http = HttpConnector::new();
    http.enforce_http(false);
    http.set_connect_timeout(Some(duration_from_secs(options.connect_timeout)));

    let connector = HttpsConnectorBuilder::new()
        .with_webpki_roots()
        .https_or_http()
        .enable_http1()
        .wrap_connector(http);

    let mut builder = Client::builder(TokioExecutor::new());
    builder.pool_max_idle_per_host(if options.keepalive {
        options.max_connections_per_host
    } else {
        0
    });
    builder.pool_idle_timeout(duration_from_secs(options.idle_timeout));
    builder.build(connector)
}

fn duration_from_secs(seconds: f64) -> Duration {
    Duration::from_secs_f64(seconds.max(0.0))
}
