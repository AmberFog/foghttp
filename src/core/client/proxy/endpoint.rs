use hyper::Uri;
use std::str::FromStr;

const HTTP_PROXY_ENDPOINT_SCHEME: &str = "http";

pub(crate) fn parse_proxy_endpoint(proxy_url: &str) -> Result<Uri, String> {
    let uri = Uri::from_str(proxy_url).map_err(|err| err.to_string())?;
    if uri.scheme_str() != Some(HTTP_PROXY_ENDPOINT_SCHEME) {
        return Err("proxy URL scheme must be http".to_owned());
    }
    let Some(authority) = uri.authority() else {
        return Err("proxy URL must include a host".to_owned());
    };
    if authority.as_str().contains('@') {
        return Err("proxy URL must not include userinfo".to_owned());
    }
    if let Some(path_and_query) = uri.path_and_query() {
        if path_and_query.as_str() != "/" {
            return Err("proxy URL must not include path or query".to_owned());
        }
    }
    Ok(uri)
}
