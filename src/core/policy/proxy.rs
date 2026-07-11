use super::error::PolicyError;
use crate::core::url::HttpUrl;

#[derive(Debug)]
pub(super) enum ProxyPolicy {
    Direct,
    Explicit,
    Environment {
        initial_origin: String,
        initial_route: TransportRoute,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum TransportRoute {
    Direct,
    Proxy,
}

impl ProxyPolicy {
    pub(super) fn parse(
        value: &str,
        initial_route: TransportRoute,
        initial_url: &HttpUrl,
    ) -> Result<Self, PolicyError> {
        match value {
            "direct" => Ok(Self::Direct),
            "explicit_proxy" => Ok(Self::Explicit),
            "environment_proxy" => Ok(Self::Environment {
                initial_origin: initial_url.origin(),
                initial_route,
            }),
            _ => Err(PolicyError::InvalidProxyPolicy(value.to_owned())),
        }
    }

    pub(super) fn route(&self, current_url: &HttpUrl) -> Result<TransportRoute, PolicyError> {
        match self {
            Self::Direct => Ok(TransportRoute::Direct),
            Self::Explicit => Ok(TransportRoute::Proxy),
            Self::Environment {
                initial_origin,
                initial_route,
            } if current_url.origin() == *initial_origin => Ok(*initial_route),
            Self::Environment { .. } => Err(PolicyError::ProxyRedirectPolicyRecomputeUnsupported),
        }
    }

    pub(super) fn validate_redirect(&self, next_url: &HttpUrl) -> Result<(), PolicyError> {
        match self {
            Self::Direct | Self::Explicit => Ok(()),
            Self::Environment { initial_origin, .. } if next_url.origin() == *initial_origin => {
                Ok(())
            }
            Self::Environment { .. } => Err(PolicyError::ProxyRedirectPolicyRecomputeUnsupported),
        }
    }
}
