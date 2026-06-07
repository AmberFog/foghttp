use crate::messages::{
    PROXY_ENDPOINT_MISSING_HOST, PROXY_ENDPOINT_PATH_OR_QUERY_UNSUPPORTED,
    PROXY_ENDPOINT_SCHEME_UNSUPPORTED, PROXY_ENDPOINT_USERINFO_UNSUPPORTED,
};
use hyper::Uri;
use std::str::FromStr;

const HTTP_PROXY_ENDPOINT_SCHEME: &str = "http";

pub(crate) fn parse_proxy_endpoint(proxy_url: &str) -> Result<Uri, String> {
    let uri = Uri::from_str(proxy_url).map_err(|err| err.to_string())?;
    if uri.scheme_str() != Some(HTTP_PROXY_ENDPOINT_SCHEME) {
        return Err(PROXY_ENDPOINT_SCHEME_UNSUPPORTED.to_owned());
    }
    let Some(authority) = uri.authority() else {
        return Err(PROXY_ENDPOINT_MISSING_HOST.to_owned());
    };
    if authority.as_str().contains('@') {
        return Err(PROXY_ENDPOINT_USERINFO_UNSUPPORTED.to_owned());
    }
    if let Some(path_and_query) = uri.path_and_query() {
        if path_and_query.as_str() != "/" {
            return Err(PROXY_ENDPOINT_PATH_OR_QUERY_UNSUPPORTED.to_owned());
        }
    }
    Ok(uri)
}
