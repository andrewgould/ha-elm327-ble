"""Load the modules that have no Home Assistant imports straight from their files.

They become members of a stand-in package so their relative imports work without
running the integration's __init__.py.
"""

import importlib.util
import pathlib
import sys
import types

_dir = pathlib.Path(__file__).parents[1] / "custom_components/elm327_ble"
_package = types.ModuleType("elm327_ble")
_package.__path__ = [str(_dir)]
sys.modules["elm327_ble"] = _package


def load(name):
    if (module := sys.modules.get(f"elm327_ble.{name}")) is not None:
        return module
    spec = importlib.util.spec_from_file_location(f"elm327_ble.{name}", _dir / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up while decorating
    spec.loader.exec_module(module)
    return module
