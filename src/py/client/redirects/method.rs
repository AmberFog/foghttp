use crate::core::method::{GET, HEAD, POST, QUERY};
use hyper::StatusCode;

pub fn redirect_method(method: &str, status_code: StatusCode) -> Option<(&'static str, bool)> {
    match (method, status_code) {
        (GET, _) => Some((GET, true)),
        (HEAD, _) => Some((HEAD, true)),
        (POST, StatusCode::MOVED_PERMANENTLY | StatusCode::FOUND | StatusCode::SEE_OTHER) => {
            Some((GET, false))
        }
        (POST, StatusCode::TEMPORARY_REDIRECT | StatusCode::PERMANENT_REDIRECT) => {
            Some((POST, true))
        }
        (
            QUERY,
            StatusCode::MOVED_PERMANENTLY
            | StatusCode::FOUND
            | StatusCode::TEMPORARY_REDIRECT
            | StatusCode::PERMANENT_REDIRECT,
        ) => Some((QUERY, true)),
        (QUERY, StatusCode::SEE_OTHER) => Some((GET, false)),
        _ => None,
    }
}
