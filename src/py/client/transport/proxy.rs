use crate::core::url::HttpUrl;
use crate::errors::FogHttpError;
use crate::messages::{
    HTTPS_PROXY_CONNECT_UNSUPPORTED, PROXY_REDIRECT_POLICY_RECOMPUTE_UNSUPPORTED,
};
use pyo3::prelude::*;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum ProxyTransportPolicy {
    Direct,
    ExplicitProxy,
    EnvironmentProxy,
}

impl ProxyTransportPolicy {
    pub(super) fn parse(value: &str) -> PyResult<Self> {
        match value {
            "direct" => Ok(Self::Direct),
            "explicit_proxy" => Ok(Self::ExplicitProxy),
            "environment_proxy" => Ok(Self::EnvironmentProxy),
            _ => Err(FogHttpError::new_err(format!(
                "unknown proxy transport policy: {value}"
            ))),
        }
    }

    pub(super) fn use_http_proxy(
        self,
        initial_use_http_proxy: bool,
        initial_origin: &str,
        current_url: &HttpUrl,
    ) -> PyResult<bool> {
        match self {
            Self::Direct => Ok(false),
            Self::ExplicitProxy => explicit_proxy_for(current_url),
            Self::EnvironmentProxy => {
                environment_proxy_for(initial_use_http_proxy, initial_origin, current_url)
            }
        }
    }

    pub(super) fn validate_redirect(
        self,
        initial_origin: &str,
        next_url: &HttpUrl,
    ) -> PyResult<()> {
        match self {
            Self::Direct => Ok(()),
            Self::ExplicitProxy => explicit_proxy_for(next_url).map(|_| ()),
            Self::EnvironmentProxy if next_url.origin() == initial_origin => Ok(()),
            Self::EnvironmentProxy => Err(FogHttpError::new_err(
                PROXY_REDIRECT_POLICY_RECOMPUTE_UNSUPPORTED,
            )),
        }
    }
}

fn explicit_proxy_for(current_url: &HttpUrl) -> PyResult<bool> {
    if current_url.scheme() == "http" {
        return Ok(true);
    }
    Err(FogHttpError::new_err(HTTPS_PROXY_CONNECT_UNSUPPORTED))
}

fn environment_proxy_for(
    initial_use_http_proxy: bool,
    initial_origin: &str,
    current_url: &HttpUrl,
) -> PyResult<bool> {
    if current_url.origin() == initial_origin {
        return Ok(initial_use_http_proxy);
    }
    Err(FogHttpError::new_err(
        PROXY_REDIRECT_POLICY_RECOMPUTE_UNSUPPORTED,
    ))
}
