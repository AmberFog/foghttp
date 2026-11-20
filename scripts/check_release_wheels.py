import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tomllib


PLATFORM_TAGS = {
    "Linux x86_64": r"manylinux(?:2014|_2_17)_x86_64",
    "Linux aarch64": r"manylinux(?:2014|_2_17)_aarch64",
    "macOS x86_64": r"macosx_[0-9]+_[0-9]+_x86_64",
    "macOS arm64": r"macosx_[0-9]+_[0-9]+_arm64",
    "Windows x64": r"win_amd64",
}


def require_release_platforms(wheels: list[Path]) -> None:
    # The audit environment includes packaging via abi3audit. Publication only compares the digest.
    from packaging.version import Version  # noqa: PLC0415

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    prefix = f"{project['name']}-{Version(project['version'])}-cp311-abi3-"
    missing = set(PLATFORM_TAGS)
    for wheel in wheels:
        if not wheel.name.startswith(prefix):
            message = f"unexpected release file: {wheel.name}"
            raise SystemExit(message)
        tags = wheel.stem.removeprefix(prefix).split(".")
        platform = next(
            (name for name, pattern in PLATFORM_TAGS.items() if all(re.fullmatch(pattern, tag) for tag in tags)),
            None,
        )
        if platform not in missing:
            message = f"unexpected or duplicate release wheel platform: {wheel.name}"
            raise SystemExit(message)
        missing.remove(platform)
    if missing:
        message = f"missing release wheels: {', '.join(sorted(missing))}"
        raise SystemExit(message)


def inventory_digest(wheels: list[Path]) -> str:
    checksums = {}
    for wheel in wheels:
        if not wheel.is_file() or wheel.is_symlink() or wheel.suffix != ".whl":
            message = f"unexpected release file: {wheel.name}"
            raise SystemExit(message)
        with wheel.open("rb") as stream:
            checksums[wheel.name] = hashlib.file_digest(stream, "sha256").hexdigest()
    return hashlib.sha256(json.dumps(checksums, sort_keys=True).encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the five FogHTTP wheels selected for release.")
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--expected-digest", help="Require the exact filenames and bytes from the ABI audit.")
    args = parser.parse_args()
    wheels = sorted(args.dist_dir.iterdir())
    digest = inventory_digest(wheels)
    if args.expected_digest is None:
        require_release_platforms(wheels)
    elif args.expected_digest != digest:
        message = "release wheels do not match the audited inventory"
        raise SystemExit(message)
    sys.stdout.write(f"{digest}\n")


if __name__ == "__main__":
    main()
