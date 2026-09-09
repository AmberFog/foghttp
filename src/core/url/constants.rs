pub(super) const HTTP_SCHEME: &str = "http";
pub(super) const HTTPS_SCHEME: &str = "https";

pub(super) const INVALID_SCHEME_ERROR: &str = "URL scheme must be http or https";
pub(super) const MISSING_HOST_ERROR: &str = "URL must include a host";

pub(super) const VALIDATED_URL_HOST_EXPECTATION: &str =
    "validated HTTP URL should always include host";
pub(super) const VALIDATED_URL_PORT_EXPECTATION: &str =
    "validated HTTP URL should always include port";
