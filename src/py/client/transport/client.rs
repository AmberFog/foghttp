use crate::core::client::HyperClient;
use crate::core::policy::TransportRoute;
use crate::errors::FogHttpError;
use pyo3::prelude::*;

#[derive(Clone)]
pub struct TransportClients {
    direct: HyperClient,
    proxy: Option<HyperClient>,
}

impl TransportClients {
    pub fn new(direct: HyperClient, proxy: Option<HyperClient>) -> Self {
        Self { direct, proxy }
    }

    pub(super) fn select(&self, route: TransportRoute) -> PyResult<HyperClient> {
        match route {
            TransportRoute::Direct => Ok(self.direct.clone()),
            TransportRoute::Proxy => self
                .proxy
                .clone()
                .ok_or_else(|| FogHttpError::new_err("proxy transport is not configured")),
        }
    }
}
