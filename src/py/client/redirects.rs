use hyper::StatusCode;

use crate::core::headers::HeaderPairs;

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

    Some(RedirectAction {
        method: next_method.to_owned(),
        preserve_body,
        url: join_url(url, location),
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

fn join_url(url: &str, location: &str) -> String {
    if location.starts_with("http://") || location.starts_with("https://") {
        return location.to_owned();
    }

    let Some(scheme_end) = url.find("://") else {
        return location.to_owned();
    };
    let origin_start = scheme_end + 3;
    let path_start = url[origin_start..]
        .find('/')
        .map_or(url.len(), |index| origin_start + index);
    let origin = &url[..path_start];

    if location.starts_with('/') {
        return format!("{origin}{location}");
    }

    let path = &url[path_start..];
    let directory_end = path
        .rfind('/')
        .map_or(path_start, |index| path_start + index + 1);
    format!("{}{}", &url[..directory_end], location)
}
