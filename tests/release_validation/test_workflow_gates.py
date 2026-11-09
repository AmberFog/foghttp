from typing import Any

import pytest

from tests.release_validation.constants import PYTHON_VERSIONS, RELEASE_CHECKS, REQUIRED_CHECKS
from tests.release_validation.workflow_assertions import named_step, required_checks


def test_ci_schedules_shared_quality_checks_for_release_prs(workflow_documents: dict[str, dict[str, Any]]) -> None:
    workflow = workflow_documents["ci"]

    assert workflow["on"]["pull_request"]["branches"] == ["main", "release/**"]
    assert "workflow_dispatch" in workflow["on"]
    assert workflow["jobs"]["quality"]["uses"] == "./.github/workflows/full_checks.yml"
    assert workflow["jobs"]["quality"]["with"]["candidate-sha"] == "${{ github.sha }}"


def test_release_calls_same_quality_workflow_with_resolved_commit(
    workflow_documents: dict[str, dict[str, Any]],
) -> None:
    job = workflow_documents["release"]["jobs"]["full-checks"]

    assert job["uses"] == "./.github/workflows/full_checks.yml"
    assert job["needs"] == "validate-version"
    assert job["with"]["candidate-sha"] == "${{ needs.validate-version.outputs.candidate-sha }}"
    assert job.get("continue-on-error", "false") == "false"


def test_shared_quality_gate_requires_all_full_suites(workflow_documents: dict[str, dict[str, Any]]) -> None:
    workflow = workflow_documents["full_checks"]
    job = workflow["jobs"]["quality-gate"]
    verify = named_step(job, "Require every full check")

    assert workflow["on"]["workflow_call"]["inputs"]["candidate-sha"]["required"] == "true"
    assert workflow["on"]["workflow_call"]["outputs"]["candidate-sha"]["value"] == (
        "${{ jobs.quality-gate.outputs.candidate-sha }}"
    )
    assert job["needs"] == list(REQUIRED_CHECKS)
    assert job["if"] == "${{ always() }}"
    assert verify["env"]["CHECK_RESULTS"] == "${{ toJSON(needs) }}"
    assert required_checks(verify["run"]) == list(REQUIRED_CHECKS)
    assert '--needs-json "$CHECK_RESULTS"' in verify["run"]
    assert verify["run"].index("check_release_candidate.py") < verify["run"].index("GITHUB_OUTPUT")


@pytest.mark.parametrize("job_name", [*REQUIRED_CHECKS, "quality-gate"])
def test_shared_quality_jobs_pin_checkout_and_verify_identity(
    job_name: str,
    workflow_documents: dict[str, dict[str, Any]],
) -> None:
    job = workflow_documents["full_checks"]["jobs"][job_name]
    checkout = named_step(job, "Checkout")
    identity_step = "Require every full check" if job_name == "quality-gate" else "Verify candidate identity"
    identity = named_step(job, identity_step)
    setup_python = named_step(job, "Set up Python")
    expected_env = {"CANDIDATE_SHA": "${{ inputs.candidate-sha }}", "EXPECTED_SHA": "${{ github.sha }}"}
    if job_name == "quality-gate":
        expected_env["CHECK_RESULTS"] = "${{ toJSON(needs) }}"

    assert checkout["with"]["ref"] == "${{ inputs.candidate-sha }}"
    assert identity["env"] == expected_env
    assert '--candidate-sha "$CANDIDATE_SHA"' in identity["run"]
    assert '--expected-sha "$EXPECTED_SHA"' in identity["run"]
    assert '--checkout-sha "$(git rev-parse HEAD)"' in identity["run"]
    assert job["steps"].index(setup_python) < job["steps"].index(identity)
    assert job.get("continue-on-error", "false") == "false"
    assert all(step.get("continue-on-error", "false") == "false" for step in job["steps"])


def test_shared_python_suite_preserves_matrix_and_full_coverage_run(
    workflow_documents: dict[str, dict[str, Any]],
) -> None:
    job = workflow_documents["full_checks"]["jobs"]["tests"]
    plain_tests = named_step(job, "Run tests")
    covered_tests = named_step(job, "Run tests with coverage")

    assert job["strategy"]["matrix"]["python-version"] == list(PYTHON_VERSIONS)
    assert job["strategy"]["fail-fast"] == "false"
    assert plain_tests["if"] == "matrix.python-version != '3.14'"
    assert plain_tests["run"] == "uv run --locked --extra dev pytest -vv"
    assert covered_tests["if"] == "matrix.python-version == '3.14'"
    assert covered_tests["run"] == "uv run --locked --extra dev coverage run -m pytest -vv"
    assert named_step(job, "Report coverage")["run"] == "uv run --locked --extra dev coverage report -m"


def test_shared_rust_and_quality_checks_preserve_required_commands(
    workflow_documents: dict[str, dict[str, Any]],
) -> None:
    jobs = workflow_documents["full_checks"]["jobs"]

    assert named_step(jobs["rust"], "Set up Rust")["uses"] == "dtolnay/rust-toolchain@stable"
    assert named_step(jobs["rust"], "Run Rust tests")["run"] == "cargo test --locked --all-targets"
    assert named_step(jobs["rust"], "Check formatting")["run"] == "cargo fmt --check"
    assert named_step(jobs["rust"], "Run clippy")["run"] == "cargo clippy --locked --all-targets -- -D warnings"
    assert named_step(jobs["rust-msrv"], "Set up Rust MSRV")["uses"] == "dtolnay/rust-toolchain@1.88.0"
    assert named_step(jobs["rust-msrv"], "Run Rust tests at MSRV")["run"] == "cargo test --locked --all-targets"
    assert named_step(jobs["rust-msrv"], "Check release features at MSRV")["run"] == (
        "cargo check --locked --all-targets --all-features"
    )
    assert named_step(jobs["pre-commit"], "Run pre-commit hooks")["run"] == (
        "uv run --no-project --with pre-commit pre-commit run --all-files --show-diff-on-failure"
    )


def test_release_gate_requires_success_and_matching_producer_commits(
    workflow_documents: dict[str, dict[str, Any]],
) -> None:
    job = workflow_documents["release"]["jobs"]["release-gate"]
    verify = named_step(job, "Require every release check for this candidate")

    assert job["needs"] == list(RELEASE_CHECKS)
    assert job["if"] == "${{ always() }}"
    assert required_checks(verify["run"]) == list(RELEASE_CHECKS)
    assert verify["env"] == {
        "CANDIDATE_SHA": "${{ needs.validate-version.outputs.candidate-sha }}",
        "QUALITY_SHA": "${{ needs.full-checks.outputs.candidate-sha }}",
        "SDIST_SHA": "${{ needs.sdist-smoke.outputs.candidate-sha }}",
        "CHECK_RESULTS": "${{ toJSON(needs) }}",
    }
    assert '--evidence-sha "$QUALITY_SHA"' in verify["run"]
    assert '--evidence-sha "$SDIST_SHA"' in verify["run"]
    assert '--needs-json "$CHECK_RESULTS"' in verify["run"]
    assert job.get("continue-on-error", "false") == "false"
    assert all(step.get("continue-on-error", "false") == "false" for step in job["steps"])


@pytest.mark.parametrize(
    "job_name",
    [
        "linux-wheels",
        "macos-wheels",
        "windows-wheels",
        "linux-wheel-smoke",
        "macos-wheel-smoke",
        "windows-wheel-smoke",
        "sdist",
        "sdist-smoke",
        "release-gate",
        "publish",
    ],
)
def test_release_artifact_jobs_use_the_resolved_candidate(
    job_name: str,
    workflow_documents: dict[str, dict[str, Any]],
) -> None:
    job = workflow_documents["release"]["jobs"][job_name]
    checkout = named_step(job, "Checkout")
    identity_step = (
        "Require every release check for this candidate" if job_name == "release-gate" else "Verify candidate identity"
    )
    identity = named_step(job, identity_step)

    assert "validate-version" in job["needs"]
    assert checkout["with"]["ref"] == "${{ needs.validate-version.outputs.candidate-sha }}"
    assert identity["env"]["CANDIDATE_SHA"] == "${{ needs.validate-version.outputs.candidate-sha }}"
    assert '--candidate-sha "$CANDIDATE_SHA"' in identity["run"]
    assert '--expected-sha "$GITHUB_SHA"' in identity["run"]
    assert '--checkout-sha "$(git rev-parse HEAD)"' in identity["run"]
    assert job.get("continue-on-error", "false") == "false"


def test_publish_cannot_bypass_required_jobs_or_run_on_manual_dispatch(
    workflow_documents: dict[str, dict[str, Any]],
) -> None:
    workflow = workflow_documents["release"]
    job = workflow["jobs"]["publish"]

    assert "workflow_dispatch" in workflow["on"]
    assert workflow["on"]["release"]["types"] == ["published"]
    assert job["if"] == "github.event_name == 'release' && github.event.action == 'published'"
    assert job["needs"] == ["validate-version", "release-gate"]
    assert set(workflow["jobs"]["release-gate"]["needs"]) == set(RELEASE_CHECKS)
    assert set(workflow["jobs"]["sdist-smoke"]["needs"]) == {"validate-version", "sdist"}
    assert job.get("continue-on-error", "false") == "false"
    assert all(step.get("continue-on-error", "false") == "false" for step in job["steps"])


def test_publish_downloads_only_distributions_into_pypi_input(workflow_documents: dict[str, dict[str, Any]]) -> None:
    job = workflow_documents["release"]["jobs"]["publish"]
    downloads = [step["with"] for step in job["steps"] if step.get("uses") == "actions/download-artifact@v4"]

    assert [download for download in downloads if download["path"] == "dist"] == [
        {"pattern": "wheels-*", "path": "dist", "merge-multiple": "true"},
        {"name": "sdist", "path": "dist"},
    ]
    assert all(download.get("pattern") != "*" for download in downloads)
    assert named_step(job, "Download source archive identity")["with"]["path"] == "evidence"
    assert job["steps"].index(named_step(job, "Verify source archive before publication")) < job["steps"].index(
        named_step(job, "Publish package distributions to PyPI"),
    )


@pytest.mark.parametrize("job_name", ["linux-wheel-smoke", "macos-wheel-smoke", "windows-wheel-smoke"])
def test_release_native_smoke_keeps_python_matrix(
    job_name: str,
    workflow_documents: dict[str, dict[str, Any]],
) -> None:
    job = workflow_documents["release"]["jobs"][job_name]

    assert job["strategy"]["matrix"]["python-version"] == list(PYTHON_VERSIONS)
    assert job["strategy"]["fail-fast"] == "false"
    assert named_step(job, "Smoke test wheel install")["run"] == (
        "python -I -S scripts/install_wheel_smoke.py --dist-dir dist"
    )


def test_release_preserves_platform_builds_and_strict_abi_audit(workflow_documents: dict[str, dict[str, Any]]) -> None:
    jobs = workflow_documents["release"]["jobs"]

    assert jobs["linux-wheels"]["strategy"]["matrix"]["target"] == ["x86_64", "aarch64"]
    assert jobs["macos-wheels"]["strategy"]["matrix"]["platform"] == [
        {"name": "x86_64", "runner": "macos-15-intel", "target": "x86_64"},
        {"name": "aarch64", "runner": "macos-15", "target": "aarch64"},
    ]
    assert jobs["windows-wheels"]["runs-on"] == "windows-latest"
    assert named_step(jobs["audit-wheels"], "Audit stable ABI compatibility")["run"] == (
        "python -m abi3audit --strict --summary dist/*.whl"
    )
