from pathlib import Path
import subprocess
import sys

from tests.release_validation.constants import CANDIDATE_SCRIPT, CLI_TIMEOUT


def run_candidate_check(arguments: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed repository-owned CLI and bounded test arguments
        [sys.executable, "-I", str(CANDIDATE_SCRIPT), *arguments],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=CLI_TIMEOUT,
    )
