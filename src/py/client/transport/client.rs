use crate::core::client::HyperClient;
use crate::core::policy::TransportRoute;
use crate::errors::FogHttpError;
use pyo3::prelude::*;

#[derive(Clone)]
pub struct TransportClients {
    direct: HyperClient,
    direct_write_timeout: HyperClient,
    proxy: Option<HyperClient>,
    proxy_write_timeout: Option<HyperClient>,
}

impl TransportClients {
    pub fn new(
        direct: HyperClient,
        direct_write_timeout: HyperClient,
        proxy: Option<HyperClient>,
        proxy_write_timeout: Option<HyperClient>,
    ) -> Self {
        Self {
            direct,
            direct_write_timeout,
            proxy,
            proxy_write_timeout,
        }
    }

    pub(super) fn select(
        &self,
        route: TransportRoute,
        use_write_timeout_transport: bool,
    ) -> PyResult<HyperClient> {
        match route {
            TransportRoute::Direct => Ok(if use_write_timeout_transport {
                self.direct_write_timeout.clone()
            } else {
                self.direct.clone()
            }),
            TransportRoute::Proxy if use_write_timeout_transport => self
                .proxy_write_timeout
                .clone()
                .ok_or_else(|| FogHttpError::new_err("proxy transport is not configured")),
            TransportRoute::Proxy => self
                .proxy
                .clone()
                .ok_or_else(|| FogHttpError::new_err("proxy transport is not configured")),
        }
    }
}
