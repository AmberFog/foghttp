use crate::errors::FogHttpLifecycleError;
use pyo3::PyErr;

pub type ProcessId = u32;

pub fn current_process_id() -> ProcessId {
    std::process::id()
}

pub fn client_used_after_fork(
    created_process_id: ProcessId,
    current_process_id: ProcessId,
) -> PyErr {
    resource_used_after_fork("client", created_process_id, current_process_id)
}

pub fn stream_response_used_after_fork(
    created_process_id: ProcessId,
    current_process_id: ProcessId,
) -> PyErr {
    resource_used_after_fork("stream response", created_process_id, current_process_id)
}

fn resource_used_after_fork(
    resource: &str,
    created_process_id: ProcessId,
    current_process_id: ProcessId,
) -> PyErr {
    FogHttpLifecycleError::new_err(format!(
        "FogHTTP {resource} was created in process {created_process_id} and cannot be used in forked process {current_process_id}; create a new client after fork",
    ))
}
