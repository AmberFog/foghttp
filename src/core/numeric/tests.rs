use super::{duration_from_secs, validate_optional_usize_option, validate_usize_option};

#[test]
fn duration_from_secs_rejects_non_finite_values() {
    for value in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        let err = duration_from_secs("Timeouts.total", value).expect_err("invalid duration");

        assert_eq!(
            err,
            "Timeouts.total must be a finite number between 0 and 2147483647"
        );
    }
}

#[test]
fn duration_from_secs_rejects_negative_values() {
    let err = duration_from_secs("Timeouts.pool", -0.1).expect_err("invalid duration");

    assert_eq!(
        err,
        "Timeouts.pool must be a finite number between 0 and 2147483647"
    );
}

#[test]
fn duration_from_secs_rejects_too_large_values() {
    let err =
        duration_from_secs("Limits.idle_timeout", 2_147_483_648.0).expect_err("invalid duration");

    assert_eq!(
        err,
        "Limits.idle_timeout must be a finite number between 0 and 2147483647"
    );
}

#[test]
fn validate_usize_option_rejects_too_large_values() {
    let err = validate_usize_option("Limits.max_active_requests", 2_147_483_648)
        .expect_err("invalid integer option");

    assert_eq!(
        err,
        "Limits.max_active_requests must be an integer between 0 and 2147483647"
    );
}

#[test]
fn validate_optional_usize_option_accepts_none() {
    assert_eq!(
        validate_optional_usize_option("Limits.max_active_requests_per_origin", None),
        Ok(None)
    );
}
