use super::RawStreamResponse;
use crate::core::metrics::Metrics;
use crate::core::response::BufferedBodyBudget;
use crate::errors::FogHttpLifecycleError;
use crate::py::client::future::PythonFutureSetters;
use crate::py::client::process::current_process_id;
use crate::py::response::{RawRequestInfo, RawResponse, RawResponseParts};
use pyo3::prelude::*;
use pyo3::types::PyList;
use std::sync::{Arc, Once};

fn initialize_python() {
    static PYTHON: Once = Once::new();
    PYTHON.call_once(Python::initialize);
}

fn request_info() -> RawRequestInfo {
    RawRequestInfo {
        method: "GET".to_string(),
        url: "http://example.com/start".to_string(),
        headers: Vec::new(),
        sensitive_headers: Vec::new(),
    }
}

fn history_response(
    budget: &BufferedBodyBudget,
    content: &[u8],
    history: Vec<RawResponse>,
) -> RawResponse {
    let mut reservation = budget.start_response();
    reservation.reserve_chunk(content.len()).unwrap();
    RawResponse::from_parts(RawResponseParts {
        status_code: 302,
        headers: vec![("location".to_string(), "/final".to_string())],
        content: content.to_vec(),
        url: "http://example.com/start".to_string(),
        request: request_info(),
        http_version: "HTTP/1.1".to_string(),
        elapsed: 0.25,
        history,
        retry_trace: None,
        body_reservation: Some(reservation),
    })
}

fn stream_response(py: Python<'_>, history: Vec<RawResponse>) -> RawStreamResponse {
    RawStreamResponse {
        status_code: 200,
        headers: Vec::new(),
        url: "http://example.com/final".to_string(),
        request: request_info(),
        http_version: "HTTP/1.1".to_string(),
        elapsed: 0.5,
        history,
        retry_trace: None,
        state: None,
        runtime_handle: None,
        future_setters: PythonFutureSetters::unused_for_test(py),
        process_id: current_process_id(),
    }
}

#[test]
fn take_history_moves_payloads_and_reservations_through_pyo3() {
    initialize_python();
    Python::attach(|py| -> PyResult<()> {
        let metrics = Arc::new(Metrics::default());
        let budget = BufferedBodyBudget::new(None, Arc::clone(&metrics));
        let nested = history_response(&budget, b"nested", Vec::new());
        let nested_payload = nested.content.as_ptr();
        let first = history_response(&budget, b"first", vec![nested]);
        let first_payload = first.content.as_ptr();
        let second = history_response(&budget, b"second", Vec::new());
        let second_payload = second.content.as_ptr();
        let stream = Bound::new(py, stream_response(py, vec![first, second]))?;
        assert_eq!(stream.borrow().redirect_hop(), 2);

        let snapshot = stream.getattr("history")?.cast_into::<PyList>()?;
        let cloned_first = snapshot.get_item(0)?.extract::<PyRef<'_, RawResponse>>()?;
        assert_eq!(cloned_first.content, b"first");
        assert_ne!(cloned_first.content.as_ptr(), first_payload);
        assert_ne!(cloned_first.history[0].content.as_ptr(), nested_payload);
        drop(cloned_first);
        drop(snapshot);
        assert_eq!(metrics.snapshot().buffered_response_bytes, 17);

        let history = stream.call_method0("take_history")?.cast_into::<PyList>()?;
        assert_eq!(history.len(), 2);
        assert!(stream.borrow().history.is_empty());
        assert_eq!(metrics.snapshot().buffered_response_bytes, 17);
        let moved_first = history.get_item(0)?.extract::<PyRef<'_, RawResponse>>()?;
        assert_eq!(moved_first.content.as_ptr(), first_payload);
        assert_eq!(moved_first.history[0].content.as_ptr(), nested_payload);
        assert_eq!(moved_first.status_code, 302);
        assert_eq!(moved_first.headers[0].1, "/final");
        drop(moved_first);
        let moved_second = history.get_item(1)?.extract::<PyRef<'_, RawResponse>>()?;
        assert_eq!(moved_second.content.as_ptr(), second_payload);
        drop(moved_second);

        let repeated = stream.call_method0("take_history")?.cast_into::<PyList>()?;
        assert!(repeated.is_empty());
        stream.call_method0("release_buffered_body_reservations")?;
        assert_eq!(metrics.snapshot().buffered_response_bytes, 17);
        drop(stream);
        assert_eq!(metrics.snapshot().buffered_response_bytes, 17);

        let first = history.get_item(0)?;
        first.call_method0("release_buffered_body_reservations")?;
        first.call_method0("release_buffered_body_reservations")?;
        assert_eq!(metrics.snapshot().buffered_response_bytes, 6);
        let released_first = first.extract::<PyRef<'_, RawResponse>>()?;
        assert_eq!(released_first.content, b"first");
        assert_eq!(released_first.history[0].content, b"nested");
        drop(released_first);
        history
            .get_item(1)?
            .call_method0("release_buffered_body_reservations")?;
        assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
        Ok(())
    })
    .unwrap();
}

#[test]
fn releasing_stream_reservations_preserves_payloads_for_later_handoff() {
    initialize_python();
    Python::attach(|py| -> PyResult<()> {
        let metrics = Arc::new(Metrics::default());
        let budget = BufferedBodyBudget::new(None, Arc::clone(&metrics));
        let nested = history_response(&budget, b"nested", Vec::new());
        let first = history_response(&budget, b"first", vec![nested]);
        let payload = first.content.as_ptr();
        let mut stream = stream_response(py, vec![first]);

        stream.release_buffered_body_reservations()?;
        stream.release_buffered_body_reservations()?;

        assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
        assert_eq!(stream.history[0].content.as_ptr(), payload);
        assert_eq!(stream.history[0].content, b"first");
        assert_eq!(stream.history[0].history[0].content, b"nested");
        let history = stream.take_history()?;
        assert_eq!(history[0].content.as_ptr(), payload);
        drop(history);
        assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
        Ok(())
    })
    .unwrap();
}

#[test]
fn take_history_rejects_inherited_process_without_changing_ownership() {
    initialize_python();
    Python::attach(|py| -> PyResult<()> {
        let metrics = Arc::new(Metrics::default());
        let budget = BufferedBodyBudget::new(None, Arc::clone(&metrics));
        let first = history_response(&budget, b"first", Vec::new());
        let payload = first.content.as_ptr();
        let mut stream = stream_response(py, vec![first]);
        stream.process_id = current_process_id().wrapping_add(1);

        let Err(error) = stream.take_history() else {
            panic!("inherited stream must reject history handoff");
        };
        assert!(error.is_instance_of::<FogHttpLifecycleError>(py));
        assert_eq!(stream.history[0].content.as_ptr(), payload);
        assert_eq!(metrics.snapshot().buffered_response_bytes, 5);
        stream.process_id = current_process_id();
        drop(stream);
        assert_eq!(metrics.snapshot().buffered_response_bytes, 0);
        Ok(())
    })
    .unwrap();
}
