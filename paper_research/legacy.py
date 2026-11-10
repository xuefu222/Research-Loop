"""复用已经逐步讲解过的工具，保持它们可独立运行。"""
import importlib.util
from functools import lru_cache
from .config import SKILL


@lru_cache(maxsize=8)
def tool(name):
    path = SKILL / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"paper_tool_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
