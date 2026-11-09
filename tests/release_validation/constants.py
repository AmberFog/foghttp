from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CANDIDATE_SCRIPT = PROJECT_ROOT / "scripts" / "check_release_candidate.py"
CANDIDATE_SHA = "a" * 40
OTHER_SHA = "b" * 40
REQUIRED_CHECKS = ("pre-commit", "rust", "rust-msrv", "tests")
RELEASE_CHECKS = (
    "validate-version",
    "full-checks",
    "audit-wheels",
    "linux-wheel-smoke",
    "macos-wheel-smoke",
    "windows-wheel-smoke",
    "sdist-smoke",
)
PYTHON_VERSIONS = ("3.11", "3.12", "3.13", "3.14", "3.15")
CLI_TIMEOUT = 10
