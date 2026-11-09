from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import tarfile


CANDIDATE_SHA = "f" * 40
LOCK_CONTENT = b'version = 4\n[[package]]\nname = "foghttp"\nversion = "0.4.2"\n'
WHEEL_NAME = "foghttp-0.4.2-cp311-abi3-test.whl"
WHEEL_CONTENT = b"rebuilt-wheel"
BUILD_PROCESS_COUNT = 2
SMOKE_PROCESS_COUNT = 3


@dataclass(frozen=True)
class SdistCase:
    dist_dir: Path
    archive: Path
    manifest: Path
    receipt: Path


def write_archive(path: Path, lock_content: bytes | None = LOCK_CONTENT, *, symlink: bool = False) -> None:
    with tarfile.open(path, "w:gz") as archive:
        metadata = tarfile.TarInfo("foghttp-0.4.2/pyproject.toml")
        archive.addfile(metadata, io.BytesIO())
        if lock_content is None:
            return
        member = tarfile.TarInfo("foghttp-0.4.2/Cargo.lock")
        if symlink:
            member.type = tarfile.SYMTYPE
            member.linkname = "../Cargo.lock"
            archive.addfile(member)
        else:
            member.size = len(lock_content)
            archive.addfile(member, io.BytesIO(lock_content))


def write_manifest(case: SdistCase, **overrides: object) -> None:
    manifest = {
        "candidate_sha": CANDIDATE_SHA,
        "archive": case.archive.name,
        "archive_sha256": hashlib.sha256(case.archive.read_bytes()).hexdigest(),
    }
    manifest.update(overrides)
    case.manifest.write_text(json.dumps(manifest), encoding="utf-8")
