use hyper::StatusCode;

use crate::core::headers::HeaderPairs;
use crate::core::url::HttpUrl;

const METHOD_GET: &str = "GET";
const METHOD_HEAD: &str = "HEAD";
const METHOD_POST: &str = "POST";

pub struct RedirectAction {
    pub method: String,
    pub preserve_body: bool,
    pub url: String,
}

pub fn redirect_action(
    method: &str,
    url: &str,
    status_code: u16,
    headers: &[(String, String)],
) -> Option<RedirectAction> {
    let status_code = redirect_status_code(status_code)?;
    let location = header_value(headers, "location")?;
    let (next_method, preserve_body) = redirect_method(method, status_code)?;
    let url = HttpUrl::parse(url).ok()?.join(location).ok()?;

    Some(RedirectAction {
        method: next_method.to_owned(),
        preserve_body,
        url: url.as_str().to_owned(),
    })
}

pub fn headers_without_body_fields(headers: HeaderPairs) -> HeaderPairs {
    headers
        .into_iter()
        .filter(|(name, _value)| {
            let name = name.to_ascii_lowercase();
            !matches!(
                name.as_str(),
                "content-encoding" | "content-length" | "content-type" | "transfer-encoding"
            )
        })
        .collect()
}

fn header_value<'a>(headers: &'a [(String, String)], name: &str) -> Option<&'a str> {
    headers
        .iter()
        .rev()
        .find(|(header_name, _value)| header_name.eq_ignore_ascii_case(name))
        .map(|(_name, value)| value.as_str())
}

fn redirect_status_code(status_code: u16) -> Option<StatusCode> {
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

fn redirect_method(method: &str, status_code: StatusCode) -> Option<(&'static str, bool)> {
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
