use hyper::StatusCode;

const METHOD_GET: &str = "GET";
const METHOD_HEAD: &str = "HEAD";
const METHOD_POST: &str = "POST";

pub fn redirect_method(method: &str, status_code: StatusCode) -> Option<(&'static str, bool)> {
    match (method, status_code) {
        (METHOD_GET, _) => Some((METHOD_GET, true)),
        (METHOD_HEAD, _) => Some((METHOD_HEAD, true)),
        (
            METHOD_POST,
            StatusCode::MOVED_PERMANENTLY | StatusCode::FOUND | StatusCode::SEE_OTHER,
        ) => Some((METHOD_GET, false)),
        (METHOD_POST, StatusCode::TEMPORARY_REDIRECT | StatusCode::PERMANENT_REDIRECT) => {
            Some((METHOD_POST, true))
        }
        _ => None,
    }
}
