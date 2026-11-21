from pathlib import Path

import pytest

from .archives import SdistCase, write_archive, write_manifest
from .processes import RecordedProcesses


@pytest.fixture
def sdist_case(tmp_path: Path) -> SdistCase:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    case = SdistCase(
        dist_dir=dist_dir,
        archive=dist_dir / "foghttp-0.4.2.tar.gz",
        manifest=tmp_path / "sdist-provenance.json",
        receipt=tmp_path / "sdist-rebuilt.json",
    )
    write_archive(case.archive)
    write_manifest(case)
    return case


@pytest.fixture
def recorded_processes(monkeypatch: pytest.MonkeyPatch) -> RecordedProcesses:
    processes = RecordedProcesses()
    monkeypatch.setattr("scripts.check_sdist.subprocess.run", processes)
    return processes
