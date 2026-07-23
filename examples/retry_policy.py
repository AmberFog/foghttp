# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "foghttp",
# ]
#
# [tool.uv.sources]
# foghttp = { path = "../", editable = true }
# ///

import foghttp


def main() -> None:
    retry = foghttp.RetryPolicy(
        retries=2,
        backoff=0.0,
        jitter=0.0,
    )
    with foghttp.Client(retry=retry) as client:
        response = client.get("https://httpbin.org/status/503")

    trace = response.retry_trace
    if trace is None:
        msg = "retry-enabled requests must expose a trace"
        raise RuntimeError(msg)

    print("final status:", response.status_code)
    for attempt in trace.attempts:
        print(
            "attempt:",
            attempt.attempt,
            "decision:",
            attempt.decision,
            "reason:",
            attempt.reason,
        )


if __name__ == "__main__":
    main()
