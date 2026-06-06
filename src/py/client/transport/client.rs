use crate::core::client::HyperClient;
use crate::errors::FogHttpError;
use pyo3::prelude::*;

#[derive(Clone)]
pub struct TransportClients {
    direct: HyperClient,
    http_proxy: Option<HyperClient>,
}

impl TransportClients {
    pub fn new(direct: HyperClient, http_proxy: Option<HyperClient>) -> Self {
        Self { direct, http_proxy }
    }

    pub(super) fn select(&self, use_http_proxy: bool) -> PyResult<HyperClient> {
        if !use_http_proxy {
            return Ok(self.direct.clone());
        }
        self.http_proxy
            .clone()
            .ok_or_else(|| FogHttpError::new_err("HTTP proxy transport is not configured"))
    }
}
