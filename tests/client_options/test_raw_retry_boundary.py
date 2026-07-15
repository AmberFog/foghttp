import math

import pytest

from foghttp import _foghttp

from .raw_options import raw_client_options


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        pytest.param(
            {"retry_retries": 2**31},
            r"RetryPolicy\.retries must be an integer between 0 and",
            id="retry-count-overflow",
        ),
        pytest.param(
            {"retry_retries": 1, "retry_backoff": math.nan},
            r"RetryPolicy\.backoff must be a finite number between 0 and",
            id="invalid-backoff",
        ),
        pytest.param(
            {"retry_retries": 1, "retry_jitter": math.inf},
            r"RetryPolicy\.jitter must be a finite number between 0 and",
            id="invalid-jitter",
        ),
        pytest.param(
            {"retry_retries": 1, "retry_statuses": (99,)},
            "statuses must contain values between 100 and 599",
            id="invalid-status",
        ),
        pytest.param(
            {"retry_retries": 1, "retry_methods": ("NOT A METHOD",)},
            "methods must contain valid HTTP method tokens",
            id="invalid-method",
        ),
    ],
)
def test_raw_client_rejects_invalid_retry_policy_without_panic(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(_foghttp.FogHttpError, match=message):
        _foghttp.RawClient(**raw_client_options(**overrides))


def test_raw_client_without_retry_ignores_retry_payload_defaults() -> None:
    client = _foghttp.RawClient(
        **raw_client_options(
            retry_retries=None,
            retry_backoff=math.nan,
            retry_jitter=math.inf,
            retry_statuses=(99,),
            retry_methods=("NOT A METHOD",),
        ),
    )

    client.close()
