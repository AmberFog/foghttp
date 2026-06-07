#[cfg(test)]
mod tests;

mod authorization;
mod endpoint;
mod http;
mod tunnel;

pub(crate) use endpoint::parse_proxy_endpoint;
pub(crate) use http::HttpProxyConnector;
pub(crate) use tunnel::{HttpsTunnelConnector, ProxyTunnelTarget};

#[cfg(test)]
use authorization::ProxyAuthorization;
#[cfg(test)]
use tunnel::{establish_tunnel, find_headers_end, parse_connect_status, tunnel_authority};
