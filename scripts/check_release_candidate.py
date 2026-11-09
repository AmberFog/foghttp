import argparse
import json
import os
from pathlib import Path
import re


def require_sha(value: str, label: str) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        message = f"{label} must be a full lowercase 40-character commit SHA"
        raise SystemExit(message)


def validate_identity(candidate: str, expected: str, checkout: str, evidence: list[str]) -> None:
    identities = [("candidate SHA", candidate), ("expected SHA", expected), ("checkout SHA", checkout)]
    identities.extend(("evidence SHA", value) for value in evidence)
    for label, value in identities:
        require_sha(value, label)
        if value != candidate:
            message = f"{label} does not match candidate SHA"
            raise SystemExit(message)


def successful_checks(needs_json: str | None, required_checks: list[str]) -> dict[str, str]:
    if needs_json is None:
        if required_checks:
            message = "required checks need --needs-json evidence"
            raise SystemExit(message)
        return {}
    if not required_checks or any(not name for name in required_checks):
        message = "needs evidence requires a nonempty list of required checks"
        raise SystemExit(message)
    try:
        needs = json.loads(needs_json)
    except json.JSONDecodeError as error:
        message = "needs evidence must be valid JSON"
        raise SystemExit(message) from error
    if not isinstance(needs, dict):
        message = "needs evidence must be an object"
        raise SystemExit(message)
    checks = {}
    for name in required_checks:
        evidence = needs.get(name)
        if not isinstance(evidence, dict) or evidence.get("result") != "success":
            message = f"required check {name!r} is missing or did not succeed"
            raise SystemExit(message)
        checks[name] = "success"
    return checks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Require exact-candidate release identity and successful checks.")
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--checkout-sha", required=True)
    parser.add_argument("--needs-json")
    parser.add_argument("--required-check", action="append", default=[])
    parser.add_argument("--evidence-sha", action="append", default=[])
    parser.add_argument("--receipt", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    validate_identity(args.candidate_sha, args.expected_sha, args.checkout_sha, args.evidence_sha)
    checks = successful_checks(args.needs_json, args.required_check)
    if args.receipt is not None:
        receipt = {"candidate_sha": args.candidate_sha, "checks": checks}
        for variable, field in [("GITHUB_RUN_ID", "run_id"), ("GITHUB_RUN_ATTEMPT", "run_attempt")]:
            if variable in os.environ:
                receipt[field] = os.environ[variable]
        args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
