import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib


SMOKE_INSTALLER = Path(__file__).with_name("install_wheel_smoke.py").resolve()


def main() -> int:
    if not sys.flags.isolated or not sys.flags.no_site:
        message = "sdist validator must run with python -I -S"
        raise SystemExit(message)

    args = parse_args()
    validate_sdist(args.dist_dir, args.manifest, args.candidate_sha, args.receipt)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild and smoke-test an exact FogHTTP sdist.")
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    return parser.parse_args()


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def find_archive(dist_dir: Path) -> Path:
    paths = sorted(dist_dir.glob("*.tar.gz"))
    if len(paths) != 1 or not paths[0].is_file() or paths[0].is_symlink():
        message = f"expected exactly one regular sdist archive in {dist_dir}"
        raise ValueError(message)
    return paths[0].resolve()


def validate_manifest(manifest_path: Path, archive: Path, candidate_sha: str) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", candidate_sha) is None:
        message = "candidate SHA must be a full lowercase Git SHA"
        raise ValueError(message)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("candidate_sha") != candidate_sha:
        message = "sdist provenance does not match the candidate SHA"
        raise ValueError(message)
    if manifest.get("archive") != archive.name:
        message = "sdist provenance does not name the selected archive"
        raise ValueError(message)
    expected_digest = manifest.get("archive_sha256")
    if not isinstance(expected_digest, str) or re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None:
        message = "sdist provenance has no valid archive SHA-256"
        raise ValueError(message)
    if sha256(archive) != expected_digest:
        message = "sdist archive SHA-256 does not match its provenance"
        raise ValueError(message)
    return expected_digest


def require_cargo_lock(archive_path: Path) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        lock_name = f"{archive_path.name.removesuffix('.tar.gz')}/Cargo.lock"
        locks = [member for member in members if member.name == lock_name]
        if len(locks) != 1 or not locks[0].isfile():
            message = "sdist must contain one regular root Cargo.lock"
            raise ValueError(message)
        lock_file = archive.extractfile(locks[0])
        if lock_file is None:
            message = "sdist Cargo.lock cannot be read"
            raise ValueError(message)
        with lock_file:
            lock = tomllib.loads(lock_file.read().decode("utf-8"))
        if not isinstance(lock.get("version"), int) or not lock.get("package"):
            message = "sdist Cargo.lock is not a populated Cargo lockfile"
            raise ValueError(message)


def run(command: list[str], *, cwd: Path) -> None:
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env["CARGO_TARGET_DIR"] = str(cwd / "cargo-target")
    subprocess.run(command, check=True, cwd=cwd, env=env)  # noqa: S603


def rebuild_and_smoke(archive: Path, workspace: Path) -> Path:
    if workspace.resolve().is_relative_to(SMOKE_INSTALLER.parent.parent):
        message = "sdist rebuild workspace must be outside the source checkout"
        raise ValueError(message)
    installer_dir = workspace / "builder"
    wheels_dir = workspace / "wheels"
    wheels_dir.mkdir()
    run([sys.executable, "-I", "-S", "-m", "venv", str(installer_dir)], cwd=workspace)
    installer_python = installer_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    run(
        [
            str(installer_python),
            "-I",
            "-m",
            "pip",
            "wheel",
            "--isolated",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--no-deps",
            "--config-settings=build-args=--locked",
            "--wheel-dir",
            str(wheels_dir),
            str(archive),
        ],
        cwd=workspace,
    )
    wheels = list(wheels_dir.glob("*.whl"))
    if len(wheels) != 1 or not wheels[0].is_file():
        message = "sdist rebuild did not produce exactly one regular wheel"
        raise ValueError(message)
    run(
        [sys.executable, "-I", "-S", str(SMOKE_INSTALLER), "--dist-dir", str(wheels_dir)],
        cwd=workspace,
    )
    return wheels[0]


def validate_sdist(dist_dir: Path, manifest: Path, candidate_sha: str, receipt: Path) -> None:
    if receipt.exists():
        message = "sdist receipt already exists; refusing to reuse stale evidence"
        raise ValueError(message)
    archive = find_archive(dist_dir)
    archive_digest = validate_manifest(manifest, archive, candidate_sha)
    require_cargo_lock(archive)
    with tempfile.TemporaryDirectory(prefix="foghttp-sdist-") as tmp_dir:
        wheel = rebuild_and_smoke(archive, Path(tmp_dir))
        if sha256(archive) != archive_digest:
            message = "sdist archive changed during rebuild or smoke"
            raise ValueError(message)
        evidence = {
            "candidate_sha": candidate_sha,
            "archive": archive.name,
            "archive_sha256": archive_digest,
            "rebuilt_wheel": wheel.name,
            "rebuilt_wheel_sha256": sha256(wheel),
            "status": "success",
        }
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
