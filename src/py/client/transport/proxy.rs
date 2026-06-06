use crate::core::url::HttpUrl;
use crate::errors::FogHttpError;
use crate::messages::PROXY_REDIRECT_POLICY_RECOMPUTE_UNSUPPORTED;
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

    pub(super) fn use_proxy_transport(
        self,
        initial_use_proxy_transport: bool,
        initial_origin: &str,
        current_url: &HttpUrl,
    ) -> PyResult<bool> {
        match self {
            Self::Direct => Ok(false),
            // Explicit `proxy=` routes every target through the proxy: plain HTTP
            // uses absolute-form, HTTPS is tunnelled via CONNECT. Both are served
            // by the proxy transport client.
            Self::ExplicitProxy => Ok(true),
            Self::EnvironmentProxy => {
                environment_proxy_for(initial_use_proxy_transport, initial_origin, current_url)
            }
        }
    }

    pub(super) fn validate_redirect(
        self,
        initial_origin: &str,
        next_url: &HttpUrl,
    ) -> PyResult<()> {
        match self {
            // Direct has no proxy decision. Explicit proxy stays a stable
            // client-level policy across hops, routing HTTP and HTTPS hops alike
            // through the same proxy.
            Self::Direct | Self::ExplicitProxy => Ok(()),
            Self::EnvironmentProxy if next_url.origin() == initial_origin => Ok(()),
            Self::EnvironmentProxy => Err(FogHttpError::new_err(
                PROXY_REDIRECT_POLICY_RECOMPUTE_UNSUPPORTED,
            )),
        }
    }
}

fn environment_proxy_for(
    initial_use_proxy_transport: bool,
    initial_origin: &str,
    current_url: &HttpUrl,
) -> PyResult<bool> {
    if current_url.origin() == initial_origin {
        return Ok(initial_use_proxy_transport);
    }
    Err(FogHttpError::new_err(
        PROXY_REDIRECT_POLICY_RECOMPUTE_UNSUPPORTED,
    ))
}
