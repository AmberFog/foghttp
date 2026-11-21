import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any

from tests.release_validation.constants import CLI_TIMEOUT


def named_step(job: dict[str, Any], name: str) -> dict[str, Any]:
    return next(step for step in job["steps"] if step.get("name") == name)


def run_python_step(step: dict[str, Any], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    if step["shell"] != "python":
        message = f"{step['name']} must use the Python shell"
        raise ValueError(message)
    return subprocess.run(  # noqa: S603 - bounded run of repository-owned workflow code in a temporary project
        [sys.executable, "-I", "-c", step["run"]],
        cwd=cwd,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
        timeout=CLI_TIMEOUT,
    )


def required_checks(command: str) -> list[str]:
    tokens = shlex.split(command.replace("\\\n", " "))
    return [tokens[index + 1] for index, argument in enumerate(tokens) if argument == "--required-check"]
