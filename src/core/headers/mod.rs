pub use request::request_headers;
pub use response::response_headers;

pub type HeaderPairs = Vec<(String, String)>;

mod request;
mod response;

#[cfg(test)]
mod tests;
