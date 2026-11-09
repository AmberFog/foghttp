from dataclasses import dataclass, field
from pathlib import Path
import subprocess

from .archives import WHEEL_CONTENT, WHEEL_NAME


ProcessCall = tuple[list[str], Path, dict[str, str]]


@dataclass
class RecordedProcesses:
    calls: list[ProcessCall] = field(default_factory=list)
    fail_on: str | None = None
    mutate_archive: Path | None = None
    wheel_count: int = 1

    def __call__(
        self,
        command: list[str],
        *,
        check: bool,
        cwd: Path,
        env: dict[str, str],
    ) -> None:
        if not check:
            message = "external commands must fail closed"
            raise AssertionError(message)
        self.calls.append((command, cwd, env))
        phase = "venv"
        if "wheel" in command:
            phase = "wheel"
        elif "--dist-dir" in command:
            phase = "smoke"
        if phase == self.fail_on:
            raise subprocess.CalledProcessError(1, command)
        if phase == "wheel":
            wheel_dir = Path(command[command.index("--wheel-dir") + 1])
            for index in range(self.wheel_count):
                name = WHEEL_NAME if index == 0 else f"extra-{index}.whl"
                (wheel_dir / name).write_bytes(WHEEL_CONTENT)
            if self.mutate_archive is not None:
                self.mutate_archive.write_bytes(b"archive mutated by external build")
