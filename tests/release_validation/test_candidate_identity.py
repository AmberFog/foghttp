import json
from pathlib import Path

import pytest

from tests.release_validation.candidate_actions import run_candidate_check
from tests.release_validation.constants import CANDIDATE_SHA, OTHER_SHA


def test_identity_only_accepts_exact_commit(identity_arguments: list[str], tmp_path: Path) -> None:
    result = run_candidate_check(identity_arguments, cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("argument", ["--candidate-sha", "--expected-sha", "--checkout-sha"])
@pytest.mark.parametrize(
    "value",
    [
        pytest.param("", id="missing-identity"),
        pytest.param("a" * 39, id="abbreviated-sha"),
        pytest.param("a" * 41, id="overlong-sha"),
        pytest.param("A" * 40, id="uppercase-sha"),
        pytest.param("g" * 40, id="non-hex-sha"),
    ],
)
def test_identity_rejects_invalid_sha(
    argument: str,
    value: str,
    identity_arguments: list[str],
    tmp_path: Path,
) -> None:
    identity_arguments[identity_arguments.index(argument) + 1] = value
    receipt = tmp_path / "rejected.json"
    result = run_candidate_check([*identity_arguments, "--receipt", str(receipt)], cwd=tmp_path)

    assert result.returncode != 0
    assert "full lowercase 40-character commit SHA" in result.stderr
    assert not receipt.exists()


@pytest.mark.parametrize("argument", ["--candidate-sha", "--expected-sha", "--checkout-sha"])
def test_identity_rejects_different_commit(
    argument: str,
    identity_arguments: list[str],
    tmp_path: Path,
) -> None:
    identity_arguments[identity_arguments.index(argument) + 1] = OTHER_SHA

    result = run_candidate_check(identity_arguments, cwd=tmp_path)

    assert result.returncode != 0
    assert "does not match candidate SHA" in result.stderr


@pytest.mark.parametrize("evidence_sha", ["", "a" * 7, OTHER_SHA])
def test_identity_rejects_bad_required_evidence(
    evidence_sha: str,
    identity_arguments: list[str],
    tmp_path: Path,
) -> None:
    result = run_candidate_check([*identity_arguments, "--evidence-sha", evidence_sha], cwd=tmp_path)

    assert result.returncode != 0
    assert "evidence SHA" in result.stderr


def test_identity_checks_every_evidence_sha(identity_arguments: list[str], tmp_path: Path) -> None:
    result = run_candidate_check(
        [*identity_arguments, "--evidence-sha", CANDIDATE_SHA, "--evidence-sha", OTHER_SHA],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "evidence SHA does not match candidate SHA" in result.stderr


def test_success_receipt_retains_candidate_checks_and_run_identity(
    check_arguments: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_RUN_ID", "123456789")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    receipt = tmp_path / "checks.json"

    result = run_candidate_check([*check_arguments, "--receipt", str(receipt)], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert json.loads(receipt.read_text()) == {
        "candidate_sha": CANDIDATE_SHA,
        "checks": {"pre-commit": "success", "rust": "success", "rust-msrv": "success", "tests": "success"},
        "run_id": "123456789",
        "run_attempt": "2",
    }
