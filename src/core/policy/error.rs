use crate::messages::{
    redirect_limit_exceeded, HTTPS_TO_HTTP_REDIRECT_BLOCKED, NON_REPLAYABLE_REQUEST_BODY_REDIRECT,
    PROXY_REDIRECT_POLICY_RECOMPUTE_UNSUPPORTED,
};
use std::error::Error;
use std::fmt::{Display, Formatter};

#[derive(Debug, Eq, PartialEq)]
pub(crate) enum PolicyError {
    InvalidProxyPolicy(String),
    RedirectLimitExceeded {
        max_redirects: usize,
        origin: String,
    },
    HttpsToHttpRedirectBlocked,
    NonReplayableRequestBodyRedirect,
    ProxyRedirectPolicyRecomputeUnsupported,
}

impl Display for PolicyError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidProxyPolicy(value) => {
                write!(formatter, "unknown proxy transport policy: {value}")
            }
            Self::RedirectLimitExceeded {
                max_redirects,
                origin,
            } => formatter.write_str(&redirect_limit_exceeded(*max_redirects, origin)),
            Self::HttpsToHttpRedirectBlocked => formatter.write_str(HTTPS_TO_HTTP_REDIRECT_BLOCKED),
            Self::NonReplayableRequestBodyRedirect => {
                formatter.write_str(NON_REPLAYABLE_REQUEST_BODY_REDIRECT)
            }
            Self::ProxyRedirectPolicyRecomputeUnsupported => {
                formatter.write_str(PROXY_REDIRECT_POLICY_RECOMPUTE_UNSUPPORTED)
            }
        }
    }
}

impl Error for PolicyError {}
