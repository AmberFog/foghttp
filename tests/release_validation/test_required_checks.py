import json
from pathlib import Path

import pytest

from tests.release_validation.candidate_actions import run_candidate_check
from tests.release_validation.constants import REQUIRED_CHECKS


@pytest.mark.parametrize("required_check", REQUIRED_CHECKS)
@pytest.mark.parametrize("result_value", ["failure", "cancelled", "skipped", "", None, True, ["success"]])
def test_gate_rejects_unsuccessful_required_check(
    required_check: str,
    result_value: object,
    check_arguments: list[str],
    tmp_path: Path,
) -> None:
    needs_index = check_arguments.index("--needs-json") + 1
    needs = json.loads(check_arguments[needs_index])
    needs[required_check]["result"] = result_value
    check_arguments[needs_index] = json.dumps(needs)
    receipt = tmp_path / "rejected.json"

    result = run_candidate_check([*check_arguments, "--receipt", str(receipt)], cwd=tmp_path)

    assert result.returncode != 0
    assert f"required check '{required_check}' is missing or did not succeed" in result.stderr
    assert not receipt.exists()


@pytest.mark.parametrize("required_check", REQUIRED_CHECKS)
def test_gate_rejects_missing_required_check(
    required_check: str,
    check_arguments: list[str],
    tmp_path: Path,
) -> None:
    needs_index = check_arguments.index("--needs-json") + 1
    needs = json.loads(check_arguments[needs_index])
    del needs[required_check]
    check_arguments[needs_index] = json.dumps(needs)

    result = run_candidate_check(check_arguments, cwd=tmp_path)

    assert result.returncode != 0
    assert f"required check '{required_check}' is missing or did not succeed" in result.stderr


@pytest.mark.parametrize("evidence", [None, "success", {}, {"outputs": {}}])
def test_gate_rejects_malformed_required_job_evidence(
    evidence: object,
    check_arguments: list[str],
    tmp_path: Path,
) -> None:
    needs_index = check_arguments.index("--needs-json") + 1
    needs = json.loads(check_arguments[needs_index])
    needs["tests"] = evidence
    check_arguments[needs_index] = json.dumps(needs)

    result = run_candidate_check(check_arguments, cwd=tmp_path)

    assert result.returncode != 0
    assert "required check 'tests' is missing or did not succeed" in result.stderr


@pytest.mark.parametrize(
    ("needs_json", "message"),
    [
        pytest.param("{", "valid JSON", id="truncated-json"),
        pytest.param("", "valid JSON", id="empty-json"),
        pytest.param("null", "must be an object", id="null-json"),
        pytest.param("[]", "must be an object", id="array-json"),
        pytest.param('"success"', "must be an object", id="string-json"),
    ],
)
def test_gate_rejects_invalid_needs_document(
    needs_json: str,
    message: str,
    check_arguments: list[str],
    tmp_path: Path,
) -> None:
    check_arguments[check_arguments.index("--needs-json") + 1] = needs_json

    result = run_candidate_check(check_arguments, cwd=tmp_path)

    assert result.returncode != 0
    assert message in result.stderr


def test_gate_does_not_accept_needs_without_required_inventory(identity_arguments: list[str], tmp_path: Path) -> None:
    result = run_candidate_check([*identity_arguments, "--needs-json", "{}"], cwd=tmp_path)

    assert result.returncode != 0
    assert "nonempty list of required checks" in result.stderr


def test_gate_does_not_accept_required_inventory_without_needs(identity_arguments: list[str], tmp_path: Path) -> None:
    result = run_candidate_check([*identity_arguments, "--required-check", "tests"], cwd=tmp_path)

    assert result.returncode != 0
    assert "need --needs-json evidence" in result.stderr


def test_gate_cannot_replace_missing_required_result_with_another_success(
    check_arguments: list[str],
    tmp_path: Path,
) -> None:
    needs_index = check_arguments.index("--needs-json") + 1
    needs = json.loads(check_arguments[needs_index])
    needs["other-tests"] = needs.pop("tests")
    check_arguments[needs_index] = json.dumps(needs)

    result = run_candidate_check(check_arguments, cwd=tmp_path)

    assert result.returncode != 0
    assert "required check 'tests'" in result.stderr
