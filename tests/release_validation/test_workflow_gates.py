import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from tests.release_validation.constants import CANDIDATE_SHA, PYTHON_VERSIONS, RELEASE_CHECKS, REQUIRED_CHECKS
from tests.release_validation.workflow_assertions import named_step, required_checks, run_python_step


EVENT_SHA_EXPRESSION = "${{ github.sha }}"


def _required_step(job: dict[str, Any], name: str) -> dict[str, Any]:
    step = named_step(job, name)
    assert "if" not in step, f"{name} must run after successful prerequisites"
    assert step.get("continue-on-error", "false") == "false", f"{name} must fail the job on error"
    return step


def _assert_event_checkout(job: dict[str, Any], identity_name: str = "Verify candidate identity") -> None:
    checkout = _required_step(job, "Checkout")
    identity = _required_step(job, identity_name)
    steps = job["steps"]
    identity_index = steps.index(identity)

    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["ref"] == EVENT_SHA_EXPRESSION
    assert steps.index(checkout) < identity_index
    assert steps.index(named_step(job, "Set up Python")) < identity_index
    assert identity["env"]["CANDIDATE_SHA"] == EVENT_SHA_EXPRESSION
    assert identity["run"].startswith("python scripts/check_release_candidate.py ")
    assert '--candidate-sha "$CANDIDATE_SHA"' in identity["run"]
    assert '--expected-sha "$GITHUB_SHA"' in identity["run"]
    assert '--checkout-sha "$(git rev-parse HEAD)"' in identity["run"]
    assert job.get("continue-on-error", "false") == "false"


def test_ci_schedules_shared_quality_checks_for_release_prs(workflow_documents: dict[str, dict[str, Any]]) -> None:
    workflow = workflow_documents["ci"]

    assert workflow["on"]["pull_request"]["branches"] == ["main", "release/**"]
    assert "workflow_dispatch" in workflow["on"]
    assert workflow["jobs"]["quality"]["uses"] == "./.github/workflows/full_checks.yml"
    assert "with" not in workflow["jobs"]["quality"]


@pytest.mark.parametrize("job_name", ["abi3-wheel", "abi3-wheel-smoke"])
def test_ci_native_jobs_verify_event_checkout(job_name: str, workflow_documents: dict[str, dict[str, Any]]) -> None:
    job = workflow_documents["ci"]["jobs"][job_name]
    assert "if" not in job
    _assert_event_checkout(job)


def test_release_calls_same_quality_workflow_for_event_commit(
    workflow_documents: dict[str, dict[str, Any]],
) -> None:
    jobs = workflow_documents["release"]["jobs"]
    job = jobs["full-checks"]

    assert job["uses"] == "./.github/workflows/full_checks.yml"
    assert job["needs"] == "validate-version"
    assert "with" not in job
    assert "outputs" not in jobs["validate-version"]
    assert job.get("continue-on-error", "false") == "false"


def test_validate_version_requires_tag_check_after_identity(workflow_documents: dict[str, dict[str, Any]]) -> None:
    job = workflow_documents["release"]["jobs"]["validate-version"]
    tag_check = _required_step(job, "Check package versions and release tag")

    assert job["steps"].index(named_step(job, "Verify candidate identity")) < job["steps"].index(tag_check)


def test_shared_quality_gate_requires_all_full_suites(workflow_documents: dict[str, dict[str, Any]]) -> None:
    workflow = workflow_documents["full_checks"]
    job = workflow["jobs"]["quality-gate"]
    verify = named_step(job, "Require every full check")

    assert "inputs" not in workflow["on"]["workflow_call"]
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
    identity_step = "Require every full check" if job_name == "quality-gate" else "Verify candidate identity"
    expected_env = {"CANDIDATE_SHA": EVENT_SHA_EXPRESSION}
    if job_name == "quality-gate":
        expected_env["CHECK_RESULTS"] = "${{ toJSON(needs) }}"

    _assert_event_checkout(job, identity_step)
    assert named_step(job, identity_step)["env"] == expected_env
    assert all(step.get("continue-on-error", "false") == "false" for step in job["steps"])


def test_shared_python_suite_preserves_matrix_and_full_coverage_run(
    workflow_documents: dict[str, dict[str, Any]],
) -> None:
    job = workflow_documents["full_checks"]["jobs"]["tests"]
    plain_tests = named_step(job, "Run tests")
    covered_tests = named_step(job, "Run tests with coverage")
    coverage_report = named_step(job, "Report coverage")

    assert job["strategy"]["matrix"]["python-version"] == list(PYTHON_VERSIONS)
    assert job["strategy"]["fail-fast"] == "false"
    assert plain_tests["if"] == "matrix.python-version != '3.14'"
    assert plain_tests["run"] == "uv run --locked --extra dev pytest -vv"
    assert covered_tests["if"] == "matrix.python-version == '3.14'"
    assert covered_tests["run"] == "uv run --locked --extra dev coverage run -m pytest -vv"
    assert coverage_report["if"] == covered_tests["if"]
    assert coverage_report["run"] == "uv run --locked --extra dev coverage report -m"


def test_shared_rust_and_quality_checks_preserve_required_commands(
    workflow_documents: dict[str, dict[str, Any]],
) -> None:
    jobs = workflow_documents["full_checks"]["jobs"]

    assert _required_step(jobs["rust"], "Set up Rust")["uses"] == "dtolnay/rust-toolchain@stable"
    assert _required_step(jobs["rust"], "Run Rust tests")["run"] == "cargo test --locked --all-targets"
    assert _required_step(jobs["rust"], "Check formatting")["run"] == "cargo fmt --check"
    assert _required_step(jobs["rust"], "Run clippy")["run"] == "cargo clippy --locked --all-targets -- -D warnings"
    assert _required_step(jobs["rust-msrv"], "Set up Rust MSRV")["uses"] == "dtolnay/rust-toolchain@1.88.0"
    assert _required_step(jobs["rust-msrv"], "Run Rust tests at MSRV")["run"] == "cargo test --locked --all-targets"
    assert _required_step(jobs["rust-msrv"], "Check release features at MSRV")["run"] == (
        "cargo check --locked --all-targets --all-features"
    )
    assert _required_step(jobs["pre-commit"], "Run pre-commit hooks")["run"] == (
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
        "CANDIDATE_SHA": EVENT_SHA_EXPRESSION,
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
        "validate-version",
        "linux-wheels",
        "macos-wheels",
        "windows-wheels",
        "linux-wheel-smoke",
        "macos-wheel-smoke",
        "windows-wheel-smoke",
        "audit-wheels",
        "sdist",
        "sdist-smoke",
        "release-gate",
        "publish",
    ],
)
def test_release_jobs_pin_checkout_and_verify_event_identity(
    job_name: str,
    workflow_documents: dict[str, dict[str, Any]],
) -> None:
    job = workflow_documents["release"]["jobs"][job_name]
    identity_step = (
        "Require every release check for this candidate" if job_name == "release-gate" else "Verify candidate identity"
    )
    if job_name not in {"validate-version", "audit-wheels"}:
        assert "validate-version" in job["needs"]
    _assert_event_checkout(job, identity_step)


@pytest.mark.parametrize(
    ("job_name", "step_name"),
    [
        ("sdist", "Record source archive identity"),
        ("sdist-smoke", "Rebuild and verify source archive"),
        ("publish", "Verify source archive before publication"),
    ],
)
def test_source_archive_provenance_uses_event_commit(
    job_name: str,
    step_name: str,
    workflow_documents: dict[str, dict[str, Any]],
) -> None:
    job = workflow_documents["release"]["jobs"][job_name]

    assert _required_step(job, step_name)["env"]["CANDIDATE_SHA"] == EVENT_SHA_EXPRESSION


def test_publish_cannot_bypass_required_jobs_or_run_on_manual_dispatch(
    workflow_documents: dict[str, dict[str, Any]],
) -> None:
    workflow = workflow_documents["release"]
    job = workflow["jobs"]["publish"]

    assert "workflow_dispatch" in workflow["on"]
    assert workflow["on"]["release"]["types"] == ["published"]
    assert job["if"] == "github.event_name == 'release' && github.event.action == 'published'"
    assert set(job["needs"]) == {"validate-version", "release-gate", "audit-wheels"}
    assert set(workflow["jobs"]["release-gate"]["needs"]) == set(RELEASE_CHECKS)
    assert set(workflow["jobs"]["sdist-smoke"]["needs"]) == {"validate-version", "sdist"}
    assert job.get("continue-on-error", "false") == "false"
    assert all(step.get("continue-on-error", "false") == "false" for step in job["steps"])


def test_publish_downloads_only_distributions_into_pypi_input(workflow_documents: dict[str, dict[str, Any]]) -> None:
    job = workflow_documents["release"]["jobs"]["publish"]
    downloads = [step["with"] for step in job["steps"] if step.get("uses") == "actions/download-artifact@v4"]

    assert [download for download in downloads if download["path"] == "dist"] == [
        {"pattern": "wheels-*", "path": "dist", "merge-multiple": "true"},
    ]
    assert all(download.get("pattern") != "*" for download in downloads)
    assert _required_step(job, "Download verified source archive")["with"] == {"name": "sdist", "path": "source-dist"}
    assert named_step(job, "Download source archive identity")["with"]["path"] == "evidence"
    assert job["steps"].index(named_step(job, "Verify source archive before publication")) < job["steps"].index(
        named_step(job, "Publish package distributions to PyPI"),
    )


@pytest.mark.parametrize("changed", [False, True], ids=["verified", "changed"])
def test_publish_admits_only_the_verified_source_archive(
    workflow_documents: dict[str, dict[str, Any]],
    tmp_path: Path,
    *,
    changed: bool,
) -> None:
    dist = tmp_path / "dist"
    source = tmp_path / "source-dist"
    evidence = tmp_path / "evidence"
    for directory in (dist, source, evidence):
        directory.mkdir()
    archive = source / "foghttp-1.2.3.tar.gz"
    original = b"source distribution"
    archive.write_bytes(b"changed" if changed else original)
    (source / "extra.whl").write_bytes(b"unverified wheel")
    manifest = {
        "archive": archive.name,
        "archive_sha256": hashlib.sha256(original).hexdigest(),
        "candidate_sha": CANDIDATE_SHA,
    }
    (evidence / "sdist-provenance.json").write_text(json.dumps(manifest))
    step = named_step(workflow_documents["release"]["jobs"]["publish"], "Verify source archive before publication")

    result = run_python_step(step, cwd=tmp_path, env={"CANDIDATE_SHA": CANDIDATE_SHA})

    if changed:
        assert result.returncode != 0
        assert "source archive does not match" in result.stderr
        assert list(dist.iterdir()) == []
    else:
        assert result.returncode == 0, result.stderr
        assert list(dist.iterdir()) == [dist / archive.name]
        assert (dist / archive.name).read_bytes() == original


def test_publish_verifies_digest_from_successful_abi_audit(workflow_documents: dict[str, dict[str, Any]]) -> None:
    jobs = workflow_documents["release"]["jobs"]
    audit = jobs["audit-wheels"]
    publish = jobs["publish"]
    download = _required_step(audit, "Download wheel artifacts")
    inventory = _required_step(audit, "Verify release wheel inventory")
    abi_check = _required_step(audit, "Audit stable ABI compatibility")
    wheels = _required_step(publish, "Download release wheels")
    verify = _required_step(publish, "Verify audited wheels before publication")
    source = _required_step(publish, "Download verified source archive")

    assert set(audit["needs"]) == {"linux-wheels", "macos-wheels", "windows-wheels"}
    assert download["with"] == wheels["with"]
    assert audit["steps"].index(download) < audit["steps"].index(inventory) < audit["steps"].index(abi_check)
    assert audit["steps"].index(_required_step(audit, "Install abi3audit")) < audit["steps"].index(inventory)
    assert audit["outputs"]["wheel-digest"] == "${{ steps.inventory.outputs.wheel-digest }}"
    assert inventory["id"] == "inventory"
    assert inventory["run"].splitlines() == [
        "digest=$(python -I scripts/check_release_wheels.py --dist-dir dist)",
        'echo "wheel-digest=$digest" >> "$GITHUB_OUTPUT"',
    ]
    assert verify["env"]["AUDITED_WHEEL_DIGEST"] == "${{ needs.audit-wheels.outputs.wheel-digest }}"
    assert verify["run"] == (
        'python -I -S scripts/check_release_wheels.py --dist-dir dist --expected-digest "$AUDITED_WHEEL_DIGEST"'
    )
    assert publish["steps"].index(wheels) < publish["steps"].index(verify) < publish["steps"].index(source)


@pytest.mark.parametrize(
    ("workflow_name", "job_name"),
    [
        ("ci", "abi3-wheel-smoke"),
        ("release", "linux-wheel-smoke"),
        ("release", "macos-wheel-smoke"),
        ("release", "windows-wheel-smoke"),
    ],
)
def test_native_smoke_requires_install_on_every_supported_python(
    workflow_name: str,
    job_name: str,
    workflow_documents: dict[str, dict[str, Any]],
) -> None:
    job = workflow_documents[workflow_name]["jobs"][job_name]

    assert job["strategy"]["matrix"]["python-version"] == list(PYTHON_VERSIONS)
    assert job["strategy"]["fail-fast"] == "false"
    assert _required_step(job, "Smoke test wheel install")["run"] == (
        "python -I -S scripts/install_wheel_smoke.py --dist-dir dist"
    )


def test_release_preserves_platform_builds(workflow_documents: dict[str, dict[str, Any]]) -> None:
    jobs = workflow_documents["release"]["jobs"]

    assert jobs["linux-wheels"]["strategy"]["matrix"]["target"] == ["x86_64", "aarch64"]
    assert jobs["macos-wheels"]["strategy"]["matrix"]["platform"] == [
        {"name": "x86_64", "runner": "macos-15-intel", "target": "x86_64"},
        {"name": "aarch64", "runner": "macos-15", "target": "aarch64"},
    ]
    assert jobs["windows-wheels"]["runs-on"] == "windows-latest"


@pytest.mark.parametrize(("workflow_name", "job_name"), [("ci", "abi3-wheel"), ("release", "audit-wheels")])
def test_abi_audit_requires_every_wheel_to_pass(
    workflow_name: str,
    job_name: str,
    workflow_documents: dict[str, dict[str, Any]],
) -> None:
    job = workflow_documents[workflow_name]["jobs"][job_name]
    assert _required_step(job, "Audit stable ABI compatibility")["run"] == (
        "python -m abi3audit --strict --summary dist/*.whl"
    )
