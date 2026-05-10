__all__ = ("validate_benchmark_args",)

from bench.models import BenchmarkArgs, Scenario


def validate_benchmark_args(
    args: BenchmarkArgs,
    *,
    requested_scenarios: list[str],
    scenario_map: dict[str, Scenario],
    concurrency_levels: list[int],
) -> None:
    errors: list[str] = []
    if args.requests < 1:
        errors.append("--requests must be >= 1")
    if args.warmup < 0:
        errors.append("--warmup must be >= 0")
    if args.repeats < 1:
        errors.append("--repeats must be >= 1")
    if args.max_redirects < 1:
        errors.append("--max-redirects must be >= 1")
    if not concurrency_levels:
        errors.append("--concurrency must contain at least one value")
    if any(value < 1 for value in concurrency_levels):
        errors.append("--concurrency values must be >= 1")

    unknown_scenarios = [name for name in requested_scenarios if name not in scenario_map]
    if unknown_scenarios:
        errors.append(f"unknown scenarios: {', '.join(unknown_scenarios)}")

    if errors:
        msg = "Invalid benchmark arguments:\n- " + "\n- ".join(errors)
        raise ValueError(msg)
