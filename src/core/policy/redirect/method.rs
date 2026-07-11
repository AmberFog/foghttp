use crate::core::method::{GET, HEAD, POST, QUERY};
use crate::core::policy::request::RequestBodyMutation;
use hyper::StatusCode;

pub(super) fn redirect_method(
    method: &str,
    status_code: StatusCode,
) -> Option<(&'static str, RequestBodyMutation)> {
    match (method, status_code) {
        (GET, _) => Some((GET, RequestBodyMutation::Preserve)),
        (HEAD, _) => Some((HEAD, RequestBodyMutation::Preserve)),
        (POST, StatusCode::MOVED_PERMANENTLY | StatusCode::FOUND | StatusCode::SEE_OTHER) => {
            Some((GET, RequestBodyMutation::Drop))
        }
        (POST, StatusCode::TEMPORARY_REDIRECT | StatusCode::PERMANENT_REDIRECT) => {
            Some((POST, RequestBodyMutation::Preserve))
        }
        (
            QUERY,
            StatusCode::MOVED_PERMANENTLY
            | StatusCode::FOUND
            | StatusCode::TEMPORARY_REDIRECT
            | StatusCode::PERMANENT_REDIRECT,
        ) => Some((QUERY, RequestBodyMutation::Preserve)),
        (QUERY, StatusCode::SEE_OTHER) => Some((GET, RequestBodyMutation::Drop)),
        _ => None,
    }
}
