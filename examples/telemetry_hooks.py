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


class PrintingTelemetrySink:
    def emit(self, event: foghttp.TelemetryEvent) -> None:
        print(
            event.event_sequence,
            event.event_type.value,
            event.mode,
            event.status_code,
            event.outcome,
            event.redacted_url,
        )


def main() -> None:
    telemetry = foghttp.TelemetryConfig(
        sink=PrintingTelemetrySink(),
        on_hook_error="warn",
    )
    with foghttp.Client(follow_redirects=True, telemetry=telemetry) as client:
        response = client.get("https://httpbin.org/redirect-to?url=/get&token=secret")
        response.raise_for_status()

        print("final:", response.url)
        print("events done")


if __name__ == "__main__":
    main()
