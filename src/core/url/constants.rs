pub(super) const HTTP_SCHEME: &str = "http";
pub(super) const HTTPS_SCHEME: &str = "https";

pub(super) const HTTP_DEFAULT_PORT: u16 = 80;
pub(super) const HTTPS_DEFAULT_PORT: u16 = 443;

pub(super) const INVALID_SCHEME_ERROR: &str = "URL scheme must be http or https";
pub(super) const MISSING_HOST_ERROR: &str = "URL must include a host";

pub(super) const VALIDATED_URL_HOST_EXPECTATION: &str =
    "validated HTTP URL should always include host";
pub(super) const VALIDATED_URL_PORT_EXPECTATION: &str =
    "validated HTTP URL should always include port";
pub(super) const VALIDATED_URL_SCHEME_EXPECTATION: &str =
    "validated HTTP URL should only use http or https";
