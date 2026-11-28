from pathlib import Path
from typing import Any

import pytest

from tests.release_validation.workflow_assertions import named_step, run_python_step


@pytest.mark.parametrize(
    ("event", "ref", "cargo_version", "dependency_version", "error"),
    [
        ("release", "refs/tags/v1.2.3", "1.2.3", "9.0.0", None),
        ("release", "refs/tags/v1.2.3", "9.0.0", "1.2.3", "release versions do not match"),
        ("release", "refs/tags/v1.2.4", "1.2.3", "1.2.4", "release versions do not match"),
        ("release", "refs/heads/release/1.2.3", "1.2.3", "9.0.0", "release workflow must run from a v* tag"),
        ("workflow_dispatch", "refs/heads/rehearsal", "1.2.3", "9.0.0", None),
        ("workflow_dispatch", "refs/heads/rehearsal", "9.0.0", "1.2.3", "release versions do not match"),
    ],
)
def test_version_gate_reads_package_version(
    event: str,
    ref: str,
    cargo_version: str,
    dependency_version: str,
    error: str | None,
    workflow_documents: dict[str, dict[str, Any]],
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n')
    (tmp_path / "Cargo.toml").write_text(
        f'[dependencies.hyper]\nversion = "{dependency_version}"\n[package]\nversion = "{cargo_version}"\n',
    )
    job = workflow_documents["release"]["jobs"]["validate-version"]
    step = named_step(job, "Check package versions and release tag")
    result = run_python_step(
        step,
        cwd=tmp_path,
        env={"GITHUB_EVENT_NAME": event, "GITHUB_REF": ref},
    )

    if error is None:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
        assert error in result.stderr
