use super::constants::{HTTPS_SCHEME, HTTP_SCHEME};

pub(super) fn is_supported(scheme: &str) -> bool {
    matches!(scheme, HTTP_SCHEME | HTTPS_SCHEME)
}
