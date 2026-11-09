import shlex
from typing import Any


def named_step(job: dict[str, Any], name: str) -> dict[str, Any]:
    return next(step for step in job["steps"] if step.get("name") == name)


def required_checks(command: str) -> list[str]:
    tokens = shlex.split(command.replace("\\\n", " "))
    return [tokens[index + 1] for index, argument in enumerate(tokens) if argument == "--required-check"]
