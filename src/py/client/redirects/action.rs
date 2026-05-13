use super::method::redirect_method;
use super::status::redirect_status_code;
use super::utils::header_value;
use crate::core::url::HttpUrl;

pub struct RedirectAction {
    pub method: String,
    pub preserve_body: bool,
    pub remove_sensitive_headers: bool,
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
    let current_url = HttpUrl::parse(url).ok()?;
    let next_url = current_url.join(location).ok()?;

    Some(RedirectAction {
        method: next_method.to_owned(),
        preserve_body,
        remove_sensitive_headers: !current_url.is_same_origin(&next_url),
        url: next_url.as_str().to_owned(),
    })
}
