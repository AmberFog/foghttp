use super::{RawRetryAttempt, RetryAttemptCompletion, RetryTraceOutcome, RetryTraceRecorder};

fn attempt(
    attempt: usize,
    decision: Option<&str>,
    completion: RetryAttemptCompletion,
) -> RawRetryAttempt {
    let elapsed = f64::from(u32::try_from(attempt).expect("test attempt fits in u32"));
    RawRetryAttempt {
        attempt,
        method: "GET".to_owned(),
        origin: "https://example.test".to_owned(),
        redirect_hop: 0,
        status_code: Some(503),
        error_type: None,
        decision: decision.map(str::to_owned),
        reason: decision.map(|_| "status".to_owned()),
        backoff: 0.0,
        decision_elapsed: decision.map(|_| elapsed),
        completed_elapsed: elapsed,
        completion,
    }
}

#[test]
fn disabled_recorder_does_not_create_a_trace() {
    let mut recorder = RetryTraceRecorder::disabled();

    recorder.record(attempt(1, Some("retry"), RetryAttemptCompletion::Complete));
    let trace = recorder.finish(
        attempt(2, None, RetryAttemptCompletion::Complete),
        RetryTraceOutcome::Response,
        Some(200),
        2.0,
    );

    assert!(trace.is_none());
}

#[test]
fn terminal_attempt_is_appended_after_a_retry() {
    let mut recorder = RetryTraceRecorder::enabled();
    recorder.record(attempt(1, Some("retry"), RetryAttemptCompletion::Complete));

    let trace = recorder
        .finish(
            attempt(2, None, RetryAttemptCompletion::Complete),
            RetryTraceOutcome::Response,
            Some(200),
            2.0,
        )
        .expect("enabled recorder must produce a trace");

    assert_eq!(trace.attempts.len(), 2);
    assert_eq!(trace.attempts[1].attempt, 2);
    assert_eq!(trace.outcome, "response");
    assert_eq!(trace.status_code, Some(200));
    assert!(!trace.terminal_error_on_last_attempt);
}

#[test]
fn terminal_result_completes_a_pending_attempt_without_duplication() {
    let mut recorder = RetryTraceRecorder::enabled();
    recorder.record(attempt(1, Some("stop"), RetryAttemptCompletion::Pending));

    let trace = recorder
        .finish(
            RawRetryAttempt {
                status_code: Some(503),
                completed_elapsed: 2.0,
                ..attempt(1, None, RetryAttemptCompletion::Complete)
            },
            RetryTraceOutcome::Error,
            None,
            2.0,
        )
        .expect("enabled recorder must produce a trace");

    assert_eq!(trace.attempts.len(), 1);
    assert_eq!(trace.attempts[0].decision.as_deref(), Some("stop"));
    assert!((trace.attempts[0].completed_elapsed - 2.0).abs() < f64::EPSILON);
    assert_eq!(trace.outcome, "error");
    assert!(trace.terminal_error_on_last_attempt);
}

#[test]
fn logical_error_after_a_completed_attempt_does_not_rewrite_it() {
    let mut recorder = RetryTraceRecorder::enabled();
    recorder.record(attempt(1, Some("retry"), RetryAttemptCompletion::Complete));

    let trace = recorder
        .finish(
            RawRetryAttempt {
                completed_elapsed: 2.0,
                ..attempt(1, None, RetryAttemptCompletion::Complete)
            },
            RetryTraceOutcome::Error,
            None,
            2.0,
        )
        .expect("enabled recorder must produce a trace");

    assert_eq!(trace.attempts.len(), 1);
    assert!((trace.attempts[0].completed_elapsed - 1.0).abs() < f64::EPSILON);
    assert!(!trace.terminal_error_on_last_attempt);
}

#[test]
fn attempt_decision_and_timing_invariants_are_explicit() {
    let decision = attempt(1, Some("retry"), RetryAttemptCompletion::Complete);
    let terminal = attempt(1, None, RetryAttemptCompletion::Complete);
    assert!(decision.has_valid_decision_state());
    assert!(terminal.has_valid_decision_state());

    let mut missing_elapsed = decision.clone();
    missing_elapsed.decision_elapsed = None;
    assert!(!missing_elapsed.has_valid_decision_state());

    let mut completed_before_decision = decision;
    completed_before_decision.completed_elapsed = 0.5;
    assert!(!completed_before_decision.has_valid_decision_state());

    let pending_terminal = attempt(1, None, RetryAttemptCompletion::Pending);
    assert!(!pending_terminal.has_valid_decision_state());
}
