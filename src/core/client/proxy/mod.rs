#[cfg(test)]
mod tests;

mod authorization;
mod endpoint;
mod http;
mod tunnel;

pub(crate) use endpoint::{parse_proxy_endpoint, proxy_endpoint_name};
pub(crate) use http::HttpProxyConnector;
pub(crate) use tunnel::{HttpsTunnelConnector, ProxyTunnelTarget};
