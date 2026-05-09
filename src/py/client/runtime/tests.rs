use super::constants::{DEFAULT_RUNTIME_WORKER_CAP, MAX_RUNTIME_WORKERS};
use super::workers::resolve_runtime_workers;

#[test]
fn auto_workers_follow_small_connection_limits() {
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
fn auto_workers_keep_zero_connection_limits_runnable() {
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
