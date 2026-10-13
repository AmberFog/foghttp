use super::{
    extract_stream_decode_content, extract_stream_decoded_byte_limit,
    extract_stream_decoder_memory_limit,
};
use crate::core::numeric::MAX_NUMERIC_OPTION;
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyInt};
use std::ffi::CString;

#[test]
fn stream_byte_limits_accept_only_valid_integer_values() {
    Python::initialize();
    Python::attach(|py| {
        for value in [0, 1, MAX_NUMERIC_OPTION] {
            let value_object = PyInt::new(py, value).into_any();
            assert_eq!(
                extract_stream_decoded_byte_limit(&value_object).unwrap(),
                Some(value)
            );
            assert_eq!(
                extract_stream_decoder_memory_limit(&value_object).unwrap(),
                value
            );
        }
        let none = py.None().into_bound(py);
        assert_eq!(extract_stream_decoded_byte_limit(&none).unwrap(), None);
        assert!(extract_stream_decoder_memory_limit(&none)
            .unwrap_err()
            .is_instance_of::<PyValueError>(py));
        for expression in [
            "True", "False", "-1", "2**31", "2**256", "1.5", "'128'", "[]", "object()",
        ] {
            let expression = CString::new(expression).unwrap();
            let value = py.eval(&expression, None, None).unwrap();
            for result in [
                extract_stream_decoded_byte_limit(&value).map(|_| ()),
                extract_stream_decoder_memory_limit(&value).map(|_| ()),
            ] {
                assert!(result.unwrap_err().is_instance_of::<PyValueError>(py));
            }
        }
    });
}

#[test]
fn stream_decode_content_rejects_truthiness_and_numpy_named_impostors() {
    Python::initialize();
    Python::attach(|py| {
        for value in [false, true] {
            let value_object = PyBool::new(py, value).to_owned().into_any();
            assert_eq!(extract_stream_decode_content(&value_object).unwrap(), value);
        }
        for expression in [
            "None",
            "0",
            "1",
            "'true'",
            "[]",
            "object()",
            "type('bool_', (), {'__module__': 'numpy', '__bool__': lambda self: True})()",
        ] {
            let expression = CString::new(expression).unwrap();
            let value = py.eval(&expression, None, None).unwrap();
            let error = extract_stream_decode_content(&value).unwrap_err();
            assert!(error.is_instance_of::<PyTypeError>(py));
            assert!(error.to_string().contains("decode_content"));
        }
    });
}
