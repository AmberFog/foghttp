import json
from typing import Any

import pytest
import yaml

from tests.release_validation.constants import CANDIDATE_SHA, PROJECT_ROOT, REQUIRED_CHECKS


@pytest.fixture
def identity_arguments() -> list[str]:
    return [
        "--candidate-sha",
        CANDIDATE_SHA,
        "--expected-sha",
        CANDIDATE_SHA,
        "--checkout-sha",
        CANDIDATE_SHA,
    ]


@pytest.fixture
def check_arguments(identity_arguments: list[str]) -> list[str]:
    needs = {name: {"result": "success", "outputs": {}} for name in REQUIRED_CHECKS}
    arguments = [*identity_arguments, "--needs-json", json.dumps(needs)]
    for name in REQUIRED_CHECKS:
        arguments.extend(["--required-check", name])
    return arguments


@pytest.fixture
def workflow_documents() -> dict[str, dict[str, Any]]:
    return {
        name: yaml.load(
            (PROJECT_ROOT / ".github" / "workflows" / f"{name}.yml").read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,  # noqa: S506 - BaseLoader cannot construct arbitrary Python objects
        )
        for name in ("ci", "full_checks", "release")
    }
