from pathlib import Path
import sys
from types import ModuleType

import pytest

from scripts.wheel_smoke_runtime import main


@pytest.mark.parametrize("native_location", ["outside", "missing"])
def test_smoke_rejects_native_extension_outside_installed_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    native_location: str,
) -> None:
    target = tmp_path / "installed"
    package = ModuleType("foghttp")
    package.__file__ = str(target / "foghttp/__init__.py")
    native = ModuleType("foghttp._foghttp")
    if native_location == "outside":
        native.__file__ = str(tmp_path / "checkout/_foghttp.abi3.so")
    modules = {"foghttp": package, "foghttp._foghttp": native}
    monkeypatch.setattr("scripts.wheel_smoke_runtime.import_module", modules.__getitem__)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "argv", ["wheel_smoke_runtime.py", str(target), str(tmp_path / "examples")])

    with pytest.raises(RuntimeError, match="native module"):
        main()
