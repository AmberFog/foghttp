use crate::core::client::HyperClient;
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

    pub(super) fn select(&self, use_http_proxy: bool) -> PyResult<HyperClient> {
        if !use_http_proxy {
            return Ok(self.direct.clone());
        }
        self.proxy
            .clone()
            .ok_or_else(|| FogHttpError::new_err("proxy transport is not configured"))
    }
}
