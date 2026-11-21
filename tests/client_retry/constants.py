__all__ = (
    "ALWAYS_CLOSE_PATH",
    "ALWAYS_STATUS_PATH",
    "ASYNC_EXPECTED_REPLAY_BODY",
    "ASYNC_STALE_REPLAY_BODY",
    "CLOSE_THEN_OK_PATH",
    "EARLY_CLOSE_THEN_OK_PATH",
    "EARLY_STATUS_THEN_OK_PATH",
    "EXPECTED_ATTEMPTS",
    "EXPECTED_REPLAY_BODY",
    "INCOMPLETE_RETRYABLE_RESPONSE_PATH",
    "STALE_REPLAY_BODY",
    "STATUS_THEN_OK_PATH",
)


ALWAYS_STATUS_PATH = "/always-status"
ALWAYS_CLOSE_PATH = "/always-close"
CLOSE_THEN_OK_PATH = "/close-then-ok"
EARLY_CLOSE_THEN_OK_PATH = "/early-close-then-ok"
EARLY_STATUS_THEN_OK_PATH = "/early-status-then-ok"
EXPECTED_ATTEMPTS = 2
EXPECTED_REPLAY_BODY = b"second-attempt-body"
STALE_REPLAY_BODY = b"stale-first-attempt-body"
ASYNC_EXPECTED_REPLAY_BODY = b"async-second-attempt-body"
ASYNC_STALE_REPLAY_BODY = b"stale-async-first-attempt-body"
INCOMPLETE_RETRYABLE_RESPONSE_PATH = "/incomplete-retryable-response"
STATUS_THEN_OK_PATH = "/status-then-ok"
