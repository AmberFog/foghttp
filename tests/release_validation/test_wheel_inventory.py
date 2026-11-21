from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

from packaging.version import Version
import pytest

from tests.release_validation.constants import CLI_TIMEOUT, PROJECT_ROOT


PLATFORMS = (
    "manylinux_2_17_x86_64.manylinux2014_x86_64",
    "manylinux_2_17_aarch64.manylinux2014_aarch64",
    "macosx_10_12_x86_64",
    "macosx_11_0_arm64",
    "win_amd64",
)


def write_wheels(dist_dir: Path, package_version: str) -> list[Path]:
    paths = [dist_dir / f"foghttp-{package_version}-cp311-abi3-{platform}.whl" for platform in PLATFORMS]
    for path in paths:
        path.write_bytes(path.name.encode())
    return paths


@pytest.fixture
def wheels(tmp_path: Path) -> list[Path]:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return write_wheels(tmp_path, str(Version(project["version"])))


def run_inventory(dist_dir: Path, *args: str, project_root: Path = PROJECT_ROOT) -> subprocess.CompletedProcess[str]:
    script = project_root / "scripts" / "check_release_wheels.py"
    isolation = ["-I", "-S"] if "--expected-digest" in args else ["-I"]
    return subprocess.run(  # noqa: S603 - fixed repository CLI with bounded test arguments
        [sys.executable, *isolation, str(script), "--dist-dir", str(dist_dir), *args],
        cwd=dist_dir,
        check=False,
        capture_output=True,
        text=True,
        timeout=CLI_TIMEOUT,
    )


def test_prerelease_wheels_use_the_normalized_version(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    shutil.copy(PROJECT_ROOT / "scripts" / "check_release_wheels.py", tmp_path / "scripts")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "foghttp"\nversion = "0.4.3-rc.1"\n')
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    write_wheels(dist_dir, "0.4.3rc1")
    audit = run_inventory(dist_dir, project_root=tmp_path)
    assert audit.returncode == 0, audit.stderr
    publish = run_inventory(dist_dir, "--expected-digest", audit.stdout.strip(), project_root=tmp_path)
    assert publish.returncode == 0, publish.stderr


def test_inventory_rejects_changed_bytes_and_missing_digest(wheels: list[Path], tmp_path: Path) -> None:
    audit = run_inventory(tmp_path)
    assert audit.returncode == 0, audit.stderr
    digest = audit.stdout.strip()
    assert run_inventory(tmp_path, "--expected-digest", digest).returncode == 0
    assert run_inventory(tmp_path, "--expected-digest", "").returncode != 0
    wheels[-1].write_bytes(b"different wheel")
    result = run_inventory(tmp_path, "--expected-digest", digest)
    assert result.returncode != 0
    assert "do not match the audited inventory" in result.stderr


def test_renaming_valid_linux_alias_changes_the_digest(wheels: list[Path], tmp_path: Path) -> None:
    original = run_inventory(tmp_path)
    assert original.returncode == 0
    linux = wheels[0]
    linux.rename(linux.with_name(linux.name.replace(".manylinux2014_x86_64", "")))
    new = run_inventory(tmp_path)
    assert new.returncode == 0
    assert new.stdout != original.stdout


@pytest.mark.parametrize("index", range(len(PLATFORMS)))
def test_missing_wheel_blocks_audit(wheels: list[Path], tmp_path: Path, index: int) -> None:
    wheels[index].unlink()
    result = run_inventory(tmp_path)
    assert result.returncode != 0
    assert "missing release wheels" in result.stderr


@pytest.mark.parametrize(
    "extra_name",
    [
        "notes.txt",
        "other-1-cp311-abi3-win_amd64.whl",
        "foghttp-1-cp311-abi3-win_amd64.whl",
    ],
)
def test_unexpected_file_blocks_audit(wheels: list[Path], extra_name: str) -> None:
    dist_dir = wheels[0].parent
    (dist_dir / extra_name).touch()
    result = run_inventory(dist_dir)
    assert result.returncode != 0
    assert "unexpected release file" in result.stderr


@pytest.mark.parametrize("bad_tags", ["manylinux_2_17_x86_64", "manylinux_2_17_x86_64.manylinux2014_aarch64"])
def test_duplicate_or_mixed_platforms_block_audit(wheels: list[Path], bad_tags: str) -> None:
    linux = wheels[0]
    linux.with_name(linux.name.replace(PLATFORMS[0], bad_tags)).touch()
    result = run_inventory(linux.parent)
    assert result.returncode != 0
    assert "unexpected or duplicate release wheel platform" in result.stderr
