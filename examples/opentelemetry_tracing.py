# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "foghttp[opentelemetry]",
#     "opentelemetry-sdk>=1.45.1,<2",
# ]
#
# [tool.uv.sources]
# foghttp = { path = "../", editable = true }
# ///

import argparse

import foghttp


def main() -> None:
    parser = argparse.ArgumentParser(description="Print FogHTTP request spans locally.")
    parser.add_argument("endpoint", help="HTTP endpoint to request, e.g. http://127.0.0.1:8000/")
    args = parser.parse_args()

    # Keep the optional SDK out of the import-only example smoke path.
    from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor  # noqa: PLC0415

    from foghttp.opentelemetry import OpenTelemetryTracing  # noqa: PLC0415

    provider = TracerProvider(shutdown_on_exit=False)
    try:
        # Console output only: no collector or network span exporter.
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        tracing = OpenTelemetryTracing(tracer_provider=provider)
        with foghttp.Client(tracing=tracing) as client:
            response = client.get(args.endpoint)
            print("status:", response.status_code)
            response.raise_for_status()
    finally:
        # The application owns SDK shutdown, after its requests and clients end.
        provider.shutdown()


if __name__ == "__main__":
    main()
