import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


DEFAULT_EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"
SMOKE_RUNTIME = Path(__file__).with_name("wheel_smoke_runtime.py").resolve()


def main() -> int:
    if not sys.flags.isolated or not sys.flags.no_site:
        msg = "wheel smoke installer must run with python -I -S"
        raise SystemExit(msg)

    args = parse_args()
    wheel_path = find_wheel(args.dist_dir)
    examples_dir = args.examples_dir.resolve()
    if not examples_dir.is_dir():
        msg = f"examples directory does not exist: {examples_dir}"
        raise SystemExit(msg)

    with tempfile.TemporaryDirectory() as tmp_dir:
        smoke_dir = Path(tmp_dir)
        installer_dir = smoke_dir / "installer"
        target_dir = smoke_dir / "site-packages"
        target_dir.mkdir()
        run(
            [sys.executable, "-I", "-S", "-m", "venv", str(installer_dir)],
            cwd=smoke_dir,
        )
        installer_python = installer_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

        run(
            [
                str(installer_python),
                "-I",
                "-m",
                "pip",
                "install",
                "--isolated",
                "--disable-pip-version-check",
                "--target",
                str(target_dir),
                str(wheel_path),
            ],
            cwd=smoke_dir,
        )
        run(
            [
                sys.executable,
                "-I",
                "-S",
                str(SMOKE_RUNTIME),
                str(target_dir),
                str(examples_dir),
            ],
            cwd=smoke_dir,
        )

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install a built FogHTTP wheel and run a smoke test.")
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--examples-dir", type=Path, default=DEFAULT_EXAMPLES_DIR)
    return parser.parse_args()


def find_wheel(dist_dir: Path) -> Path:
    wheel_paths = sorted(dist_dir.glob("*.whl"))
    if len(wheel_paths) != 1:
        msg = f"expected exactly one wheel in {dist_dir}, found {len(wheel_paths)}"
        raise SystemExit(msg)
    return wheel_paths[0].resolve()


def run(command: list[str], *, cwd: Path | None = None) -> None:
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    subprocess.run(command, check=True, cwd=cwd, env=env)  # noqa: S603


if __name__ == "__main__":
    raise SystemExit(main())
