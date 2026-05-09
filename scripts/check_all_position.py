import ast
from pathlib import Path
import sys


def main() -> int:
    errors = []
    for arg in sys.argv[1:]:
        path = Path(arg)
        if not path.exists() or path.suffix != ".py":
            continue
        errors.extend(check_file(path))

    if errors:
        sys.stderr.write("\n".join(errors) + "\n")
        return 1
    return 0


def check_file(path: Path) -> list[str]:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    all_index = all_assignment_index(module)
    if all_index is None:
        return []

    expected_index = 1 if ast.get_docstring(module) else 0
    if all_index == expected_index:
        return []

    return [f"{path}: move __all__ to the file top"]


def all_assignment_index(module: ast.Module) -> int | None:
    for index, statement in enumerate(module.body):
        if is_all_assignment(statement):
            return index
    return None


def is_all_assignment(statement: ast.stmt) -> bool:
    if isinstance(statement, ast.Assign):
        return any(isinstance(target, ast.Name) and target.id == "__all__" for target in statement.targets)
    if isinstance(statement, ast.AnnAssign):
        target = statement.target
        return isinstance(target, ast.Name) and target.id == "__all__"
    return False


if __name__ == "__main__":
    raise SystemExit(main())
