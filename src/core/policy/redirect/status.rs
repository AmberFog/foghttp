use hyper::StatusCode;

pub(super) fn redirect_status_code(status_code: u16) -> Option<StatusCode> {
    let Ok(status_code) = StatusCode::from_u16(status_code) else {
        return None;
    };

    if matches!(
        status_code,
        StatusCode::MOVED_PERMANENTLY
            | StatusCode::FOUND
            | StatusCode::SEE_OTHER
            | StatusCode::TEMPORARY_REDIRECT
            | StatusCode::PERMANENT_REDIRECT
    ) {
        Some(status_code)
    } else {
        None
    }
}
