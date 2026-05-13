pub fn header_value<'a>(headers: &'a [(String, String)], name: &str) -> Option<&'a str> {
    headers
        .iter()
        .rev()
        .find(|(header_name, _value)| header_name.eq_ignore_ascii_case(name))
        .map(|(_name, value)| value.as_str())
}
