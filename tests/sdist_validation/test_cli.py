from pathlib import Path
import subprocess
import sys

from .archives import CANDIDATE_SHA, SdistCase


SCRIPT = Path(__file__).parents[2] / "scripts/check_sdist.py"


def test_cli_requires_isolated_no_site_interpreter(sdist_case: SdistCase) -> None:
    outcome = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert outcome.returncode != 0
    assert "must run with python -I -S" in outcome.stderr
    assert not sdist_case.receipt.exists()


def test_isolated_cli_rejects_mismatched_sha_before_install(sdist_case: SdistCase) -> None:
    outcome = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-I",
            "-S",
            str(SCRIPT),
            "--dist-dir",
            str(sdist_case.dist_dir),
            "--manifest",
            str(sdist_case.manifest),
            "--candidate-sha",
            CANDIDATE_SHA.replace("f", "a"),
            "--receipt",
            str(sdist_case.receipt),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert outcome.returncode != 0
    assert "provenance does not match the candidate SHA" in outcome.stderr
    assert not sdist_case.receipt.exists()
