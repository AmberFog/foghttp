use super::constants::{
    DEFAULT_RUNTIME_WORKER_CAP, MAX_RUNTIME_WORKERS, SHARED_RUNTIME_WORKER_FALLBACK,
};
use super::workers::resolve_runtime_workers;
use super::{
    parse_runtime_mode, shared_runtime_workers_from_parallelism, ClientRuntime, RuntimeMode,
};

#[test]
fn auto_workers_follow_small_active_request_limits() {
    assert_eq!(resolve_runtime_workers(1, None, None).unwrap(), 1);
    assert_eq!(resolve_runtime_workers(4, None, None).unwrap(), 4);
}

#[test]
fn auto_workers_are_capped_at_default_cap() {
    assert_eq!(
        resolve_runtime_workers(100, None, None).unwrap(),
        DEFAULT_RUNTIME_WORKER_CAP,
    );
}

#[test]
fn auto_workers_keep_zero_active_request_limits_runnable() {
    assert_eq!(resolve_runtime_workers(0, None, None).unwrap(), 1);
}

#[test]
fn explicit_workers_override_env_workers() {
    assert_eq!(resolve_runtime_workers(100, Some(4), Some("8")).unwrap(), 4);
}

#[test]
fn env_workers_override_auto_workers() {
    assert_eq!(resolve_runtime_workers(100, None, Some("8")).unwrap(), 8);
}

#[test]
fn env_workers_allow_hard_cap() {
    assert_eq!(
        resolve_runtime_workers(100, None, Some("32")).unwrap(),
        MAX_RUNTIME_WORKERS,
    );
}

#[test]
fn rejects_zero_workers() {
    let error = resolve_runtime_workers(100, Some(0), None).unwrap_err();

    assert_eq!(error, "runtime_workers must be an integer between 1 and 32");
}

#[test]
fn rejects_workers_above_hard_cap() {
    let error = resolve_runtime_workers(100, Some(33), None).unwrap_err();

    assert_eq!(error, "runtime_workers must be an integer between 1 and 32");
}

#[test]
fn rejects_invalid_env_workers() {
    let error = resolve_runtime_workers(100, None, Some("many")).unwrap_err();

    assert_eq!(
        error,
        "FOGHTTP_RUNTIME_WORKERS must be an integer between 1 and 32",
    );
}

#[test]
fn rejects_env_workers_above_hard_cap() {
    let error = resolve_runtime_workers(100, None, Some("33")).unwrap_err();

    assert_eq!(
        error,
        "FOGHTTP_RUNTIME_WORKERS must be an integer between 1 and 32",
    );
}

#[test]
fn parses_runtime_modes() {
    assert_eq!(parse_runtime_mode("shared").unwrap(), RuntimeMode::Shared);
    assert_eq!(
        parse_runtime_mode("dedicated").unwrap(),
        RuntimeMode::Dedicated
    );
}

#[test]
fn rejects_invalid_runtime_mode() {
    pyo3::Python::initialize();
    let error = parse_runtime_mode("global").unwrap_err();

    assert!(error
        .to_string()
        .contains("runtime must be 'shared' or 'dedicated'"));
}

#[test]
fn shared_runtime_rejects_explicit_workers() {
    pyo3::Python::initialize();
    let error = pyo3::Python::attach(|py| {
        let Err(error) = ClientRuntime::build(py, 100, RuntimeMode::Shared, Some(1)) else {
            panic!("expected shared runtime to reject explicit workers");
        };
        error
    });

    assert!(error
        .to_string()
        .contains("runtime_workers requires runtime='dedicated'"));
}

#[test]
fn shared_runtime_workers_use_parallelism_when_available() {
    assert_eq!(shared_runtime_workers_from_parallelism(Some(1)), 1);
    assert_eq!(shared_runtime_workers_from_parallelism(Some(4)), 4);
}

#[test]
fn shared_runtime_workers_cap_large_parallelism() {
    assert_eq!(
        shared_runtime_workers_from_parallelism(Some(100)),
        DEFAULT_RUNTIME_WORKER_CAP,
    );
}

#[test]
fn shared_runtime_workers_fallback_is_conservative() {
    assert_eq!(
        shared_runtime_workers_from_parallelism(None),
        SHARED_RUNTIME_WORKER_FALLBACK,
    );
}

#[test]
fn clients_on_shared_runtime_share_decoder_admission_and_close_does_not_reset_it() {
    use std::sync::Arc;
    let resources = Arc::new(super::RuntimeResources::new(
        super::build_multi_thread_runtime(2).unwrap(),
    ));
    let first = ClientRuntime::Shared(Arc::clone(&resources));
    let second = ClientRuntime::Shared(resources);
    let first_gate = first.buffered_decoders();
    let second_gate = second.buffered_decoders();
    assert!(Arc::ptr_eq(&first_gate, &second_gate));
    assert_eq!(first_gate.available_permits(), 2);
    let held = first_gate.try_acquire().unwrap();
    first.shutdown_background();
    assert_eq!(second_gate.available_permits(), 1);
    drop(held);
    assert_eq!(second_gate.available_permits(), 2);
}

#[test]
fn dedicated_runtimes_have_independent_worker_sized_decoder_admission() {
    use std::sync::Arc;
    let first = ClientRuntime::Dedicated(super::RuntimeResources::new(
        super::build_multi_thread_runtime(1).unwrap(),
    ));
    let second = ClientRuntime::Dedicated(super::RuntimeResources::new(
        super::build_multi_thread_runtime(2).unwrap(),
    ));
    assert!(!Arc::ptr_eq(
        &first.buffered_decoders(),
        &second.buffered_decoders()
    ));
    assert_eq!(first.buffered_decoders().available_permits(), 1);
    assert_eq!(second.buffered_decoders().available_permits(), 2);
}
