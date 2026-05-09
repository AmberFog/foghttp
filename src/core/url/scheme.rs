use super::constants::{
    HTTPS_DEFAULT_PORT, HTTPS_SCHEME, HTTP_DEFAULT_PORT, HTTP_SCHEME,
    VALIDATED_URL_SCHEME_EXPECTATION,
};

pub(super) fn is_supported(scheme: &str) -> bool {
    matches!(scheme, HTTP_SCHEME | HTTPS_SCHEME)
}

pub(super) fn default_port(scheme: &str) -> u16 {
    match scheme {
        HTTP_SCHEME => HTTP_DEFAULT_PORT,
        HTTPS_SCHEME => HTTPS_DEFAULT_PORT,
        _ => unreachable!("{}", VALIDATED_URL_SCHEME_EXPECTATION),
    }
}
