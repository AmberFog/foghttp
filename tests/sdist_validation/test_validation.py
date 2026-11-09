import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

import pytest

from scripts.check_sdist import rebuild_and_smoke, validate_sdist

from .archives import (
    BUILD_PROCESS_COUNT,
    CANDIDATE_SHA,
    SMOKE_PROCESS_COUNT,
    WHEEL_CONTENT,
    WHEEL_NAME,
    SdistCase,
    write_archive,
    write_manifest,
)
from .processes import RecordedProcesses


def test_exact_sdist_rebuild_reuses_isolated_install_smoke(
    sdist_case: SdistCase,
    recorded_processes: RecordedProcesses,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONPATH", "/checkout")
    monkeypatch.setenv("PYTHONHOME", "/checkout/python")
    monkeypatch.setenv("CARGO_TARGET_DIR", "/checkout/target")

    validate_sdist(sdist_case.dist_dir, sdist_case.manifest, CANDIDATE_SHA, sdist_case.receipt)

    receipt = json.loads(sdist_case.receipt.read_text())
    assert receipt == {
        "candidate_sha": CANDIDATE_SHA,
        "archive": sdist_case.archive.name,
        "archive_sha256": hashlib.sha256(sdist_case.archive.read_bytes()).hexdigest(),
        "rebuilt_wheel": WHEEL_NAME,
        "rebuilt_wheel_sha256": hashlib.sha256(WHEEL_CONTENT).hexdigest(),
        "status": "success",
    }
    assert len(recorded_processes.calls) == SMOKE_PROCESS_COUNT
    build_command, workspace, build_env = recorded_processes.calls[1]
    assert build_command[-1] == str(sdist_case.archive)
    assert "--isolated" in build_command
    assert "--no-cache-dir" in build_command
    assert "--no-deps" in build_command
    assert "--no-build-isolation" not in build_command
    assert "--config-settings=build-args=--locked" in build_command
    assert "PYTHONHOME" not in build_env
    assert "PYTHONPATH" not in build_env
    assert Path(build_env["CARGO_TARGET_DIR"]).parent == workspace
    assert not workspace.is_relative_to(Path.cwd())
    assert not workspace.exists()
    smoke_command, smoke_workspace, _env = recorded_processes.calls[2]
    assert smoke_workspace == workspace
    assert smoke_command[1:3] == ["-I", "-S"]
    assert Path(smoke_command[3]).name == "install_wheel_smoke.py"
    assert list(sdist_case.dist_dir.iterdir()) == [sdist_case.archive]


@pytest.mark.parametrize(
    "overrides",
    [
        {"candidate_sha": "a" * 40},
        {"candidate_sha": None},
        {"archive": "different.tar.gz"},
        {"archive_sha256": "0" * 64},
        {"archive_sha256": "invalid"},
        {"archive_sha256": None},
    ],
    ids=["wrong-sha", "missing-sha", "wrong-archive", "wrong-digest", "invalid-digest", "missing-digest"],
)
def test_rejects_mismatched_provenance_before_build(
    sdist_case: SdistCase,
    recorded_processes: RecordedProcesses,
    overrides: dict[str, object],
) -> None:
    write_manifest(sdist_case, **overrides)

    with pytest.raises(ValueError, match="sdist"):
        validate_sdist(sdist_case.dist_dir, sdist_case.manifest, CANDIDATE_SHA, sdist_case.receipt)

    assert not recorded_processes.calls
    assert not sdist_case.receipt.exists()


@pytest.mark.parametrize("candidate_sha", ["main", "f53b525", "", "A" * 40], ids=["ref", "short", "empty", "uppercase"])
def test_requires_full_candidate_sha_before_build(
    sdist_case: SdistCase,
    recorded_processes: RecordedProcesses,
    candidate_sha: str,
) -> None:
    with pytest.raises(ValueError, match="full lowercase Git SHA"):
        validate_sdist(sdist_case.dist_dir, sdist_case.manifest, candidate_sha, sdist_case.receipt)

    assert not recorded_processes.calls
    assert not sdist_case.receipt.exists()


@pytest.mark.parametrize("archive_count", [0, 2], ids=["missing", "ambiguous"])
def test_rejects_missing_or_ambiguous_archive(
    sdist_case: SdistCase,
    recorded_processes: RecordedProcesses,
    archive_count: int,
) -> None:
    if archive_count == 0:
        sdist_case.archive.unlink()
    else:
        (sdist_case.dist_dir / "another.tar.gz").write_bytes(sdist_case.archive.read_bytes())

    with pytest.raises(ValueError, match="exactly one regular sdist"):
        validate_sdist(sdist_case.dist_dir, sdist_case.manifest, CANDIDATE_SHA, sdist_case.receipt)

    assert not recorded_processes.calls
    assert not sdist_case.receipt.exists()


@pytest.mark.parametrize("lock_content", [None, b"version = 4\n"], ids=["missing", "empty"])
def test_requires_populated_cargo_lock_before_build(
    sdist_case: SdistCase,
    recorded_processes: RecordedProcesses,
    lock_content: bytes | None,
) -> None:
    write_archive(sdist_case.archive, lock_content)
    write_manifest(sdist_case)

    with pytest.raises(ValueError, match=r"Cargo\.lock"):
        validate_sdist(sdist_case.dist_dir, sdist_case.manifest, CANDIDATE_SHA, sdist_case.receipt)

    assert not recorded_processes.calls
    assert not sdist_case.receipt.exists()


def test_rejects_symlink_cargo_lock_before_build(
    sdist_case: SdistCase,
    recorded_processes: RecordedProcesses,
) -> None:
    write_archive(sdist_case.archive, symlink=True)
    write_manifest(sdist_case)

    with pytest.raises(ValueError, match=r"regular root Cargo\.lock"):
        validate_sdist(sdist_case.dist_dir, sdist_case.manifest, CANDIDATE_SHA, sdist_case.receipt)

    assert not recorded_processes.calls
    assert not sdist_case.receipt.exists()


def test_rejects_corrupt_archive_before_build(sdist_case: SdistCase, recorded_processes: RecordedProcesses) -> None:
    sdist_case.archive.write_bytes(b"not a tar archive")
    write_manifest(sdist_case)

    with pytest.raises(tarfile.ReadError):
        validate_sdist(sdist_case.dist_dir, sdist_case.manifest, CANDIDATE_SHA, sdist_case.receipt)

    assert not recorded_processes.calls
    assert not sdist_case.receipt.exists()


@pytest.mark.parametrize("phase", ["venv", "wheel", "smoke"])
def test_external_failure_never_creates_success_receipt(
    sdist_case: SdistCase,
    recorded_processes: RecordedProcesses,
    phase: str,
) -> None:
    recorded_processes.fail_on = phase

    with pytest.raises(subprocess.CalledProcessError):
        validate_sdist(sdist_case.dist_dir, sdist_case.manifest, CANDIDATE_SHA, sdist_case.receipt)

    assert not sdist_case.receipt.exists()


@pytest.mark.parametrize("wheel_count", [0, 2], ids=["missing", "ambiguous"])
def test_rebuild_must_produce_exactly_one_wheel(
    sdist_case: SdistCase,
    recorded_processes: RecordedProcesses,
    wheel_count: int,
) -> None:
    recorded_processes.wheel_count = wheel_count

    with pytest.raises(ValueError, match="exactly one regular wheel"):
        validate_sdist(sdist_case.dist_dir, sdist_case.manifest, CANDIDATE_SHA, sdist_case.receipt)

    assert len(recorded_processes.calls) == BUILD_PROCESS_COUNT
    assert not sdist_case.receipt.exists()


def test_archive_mutation_during_build_invalidates_receipt(
    sdist_case: SdistCase,
    recorded_processes: RecordedProcesses,
) -> None:
    recorded_processes.mutate_archive = sdist_case.archive

    with pytest.raises(ValueError, match="archive changed"):
        validate_sdist(sdist_case.dist_dir, sdist_case.manifest, CANDIDATE_SHA, sdist_case.receipt)

    assert not sdist_case.receipt.exists()


def test_existing_receipt_cannot_be_reused(sdist_case: SdistCase, recorded_processes: RecordedProcesses) -> None:
    sdist_case.receipt.write_text("stale evidence")

    with pytest.raises(ValueError, match="stale evidence"):
        validate_sdist(sdist_case.dist_dir, sdist_case.manifest, CANDIDATE_SHA, sdist_case.receipt)

    assert not recorded_processes.calls
    assert sdist_case.receipt.read_text() == "stale evidence"


def test_rebuild_refuses_workspace_inside_source_checkout(
    sdist_case: SdistCase,
    recorded_processes: RecordedProcesses,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.setattr("scripts.check_sdist.SMOKE_INSTALLER", checkout / "scripts/install_wheel_smoke.py")

    with pytest.raises(ValueError, match="outside the source checkout"):
        rebuild_and_smoke(sdist_case.archive, checkout)

    assert not recorded_processes.calls
    assert not list(checkout.iterdir())
