# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""Locate the bundled ASWF MaterialX runtime for texture baking."""

from __future__ import annotations

import os
import shutil
from typing import Dict, List, Optional

_ENV_OVERRIDE = "VREDX_BAKER_ROOT"
_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
_DEV_ROOT = os.path.join(_PACKAGE_DIR, "third_party", "materialx")
_BAKER_MODULE = "vredx.baking.baketextures_runner"


def _is_inside_zip(path: str) -> bool:
    norm = os.path.normpath(path).lower()
    marker = ".zip" + os.sep
    return marker in norm or norm.endswith(".zip")


def installed_baking_runtime_dir() -> str:
    """Folder end users should move ``baking_runtime`` into (outside ScriptPlugins)."""
    return os.path.join(
        os.path.expanduser("~"), "Documents", "Autodesk", "VredX", "baking_runtime")


def shipped_baking_runtime_dir() -> str:
    """``baking_runtime`` folder shipped next to ``VredX.py`` in release zips."""
    from .. import plugin_root
    return os.path.join(plugin_root(), "baking_runtime")


def runtime_setup_message() -> str:
    """Short hint when baking UI is hidden because the runtime is not installed."""
    return (
        "Texture baking requires the ASWF MaterialX runtime.\n"
        "Move the shipped baking_runtime folder to:\n  %s"
        % installed_baking_runtime_dir())


def _installed_materialx_root() -> Optional[str]:
    path = os.path.join(installed_baking_runtime_dir(), "materialx")
    return path if os.path.isdir(path) else None


def _shipped_materialx_root() -> Optional[str]:
    path = os.path.join(shipped_baking_runtime_dir(), "materialx")
    return path if os.path.isdir(path) else None


def _dev_materialx_root() -> Optional[str]:
    if os.path.isdir(_DEV_ROOT) and not _is_inside_zip(_DEV_ROOT):
        return _DEV_ROOT
    return None


def _runtime_candidates() -> List[str]:
    """Ordered roots that count as an installed runtime for baking."""
    roots: List[str] = []
    override = os.environ.get(_ENV_OVERRIDE, "").strip()
    if override:
        roots.append(os.path.normpath(override))
    installed = _installed_materialx_root()
    if installed:
        roots.append(installed)
    dev = _dev_materialx_root()
    if dev and dev not in roots:
        roots.append(dev)
    return roots


def _valid_runtime_at(root: str) -> bool:
    if not root or _is_inside_zip(root):
        return False
    lib_dir = _materialx_python_lib_dir(root)
    if lib_dir is None or _is_inside_zip(lib_dir):
        return False
    python_exe = _find_python_in_root(root)
    return bool(python_exe and not _is_inside_zip(python_exe) and _vredx_package_available())


def vredx_import_path() -> str:
    """Path for ``import vredx`` in the baker subprocess (zip or dev checkout)."""
    from .. import plugin_root
    root = plugin_root()
    zip_path = os.path.join(root, "vredx.zip")
    if os.path.isfile(zip_path):
        return zip_path
    return root


def runtime_root() -> str:
    """Root of the ASWF MaterialX prebuilt tree (read-only vendor bundle)."""
    for root in _runtime_candidates():
        if _valid_runtime_at(root):
            return root
    shipped = _shipped_materialx_root()
    if shipped:
        return shipped
    return _DEV_ROOT


def baker_module() -> str:
    """Module name for the baker subprocess entry point (inside vredx.zip)."""
    return _BAKER_MODULE


def baker_subprocess_argv(bake_args: List[str]) -> List[str]:
    """Build argv for the baker subprocess without loose .py on disk."""
    python_exe = find_python_executable()
    if not python_exe:
        raise RuntimeError("MaterialX baker Python interpreter not found.")
    entry = vredx_import_path()
    bootstrap = (
        "import sys; sys.path.insert(0, {0!r}); "
        "from vredx.baking.baketextures_runner import main; "
        "raise SystemExit(main())".format(entry)
    )
    return [python_exe, "-c", bootstrap] + list(bake_args)


def _find_file(root: str, *relative_parts: str) -> Optional[str]:
    path = os.path.join(root, *relative_parts)
    return path if os.path.isfile(path) else None


def _find_python_in_root(root: str) -> Optional[str]:
    for parts in (
        ("python313", "python.exe"),
        ("python", "python.exe"),
        ("python", "bin", "python.exe"),
        ("bin", "python.exe"),
    ):
        found = _find_file(root, *parts)
        if found:
            return found

    if _materialx_python_lib_dir(root) is not None:
        fallback = shutil.which("python3.13") or shutil.which("python")
        if fallback:
            return fallback
    return None


def _materialx_python_lib_dir(root: Optional[str] = None) -> Optional[str]:
    """Directory containing PyMaterialX*.pyd modules."""
    root = root or runtime_root()
    candidates = [
        os.path.join(root, "python", "build", "lib"),
        os.path.join(root, "python", "MaterialX"),
        os.path.join(root, "python"),
    ]
    for path in candidates:
        mx_dir = os.path.join(path, "MaterialX")
        if os.path.isdir(mx_dir):
            render = os.path.join(mx_dir, "PyMaterialXRenderGlsl.cp313-win_amd64.pyd")
            if os.path.isfile(render):
                return path
            for name in os.listdir(mx_dir):
                if name.startswith("PyMaterialXRenderGlsl") and name.endswith(".pyd"):
                    return path
    return None


def find_python_executable() -> Optional[str]:
    """Python interpreter used to run the TextureBaker subprocess."""
    for root in _runtime_candidates():
        if _valid_runtime_at(root):
            return _find_python_in_root(root)
    return None


def find_materialx_bin_dir() -> Optional[str]:
    """Directory containing MaterialX native DLLs for PATH."""
    root = runtime_root()
    for name in ("bin", "lib"):
        path = os.path.join(root, name)
        if os.path.isdir(path):
            return path
    return None


def find_default_libraries_dir() -> Optional[str]:
    """Bundled MaterialX nodedef libraries."""
    path = os.path.join(runtime_root(), "libraries")
    return path if os.path.isdir(path) else None


def find_vred_libraries_dir() -> Optional[str]:
    """VRED-shipped MaterialX libraries when running inside VRED."""
    vred_root = os.environ.get("VRED_ROOT", "").strip()
    if not vred_root:
        return None
    path = os.path.join(vred_root, "runtimeData", "MaterialX", "libraries")
    return path if os.path.isdir(path) else None


def library_search_paths() -> List[str]:
    """Ordered search paths for MaterialX data (root folders with libraries/)."""
    paths: List[str] = []
    root = runtime_root()
    if os.path.isdir(os.path.join(root, "libraries")):
        paths.append(root)
    vred = find_vred_libraries_dir()
    if vred:
        vred_root = os.path.dirname(vred)
        if vred_root not in paths:
            paths.append(vred_root)
    return paths


def _vredx_package_available() -> bool:
    entry = vredx_import_path()
    if os.path.isfile(entry):
        return True
    return os.path.isdir(os.path.join(entry, "vredx"))


def is_runtime_available() -> bool:
    """True when the runtime is installed at the expected location (not merely shipped)."""
    return any(_valid_runtime_at(root) for root in _runtime_candidates())


def subprocess_env() -> Dict[str, str]:
    """Environment for the baker subprocess (DLL path + PYTHONPATH)."""
    env = dict(os.environ)
    root = runtime_root()
    lib_dir = _materialx_python_lib_dir()
    python_paths: List[str] = []

    vredx_path = vredx_import_path()
    if os.path.isfile(vredx_path) or os.path.isdir(vredx_path):
        python_paths.append(vredx_path)

    if lib_dir:
        python_paths.append(lib_dir)
    python_paths.extend([
        os.path.join(root, "python"),
        os.path.join(root, "python", "Lib", "site-packages"),
        os.path.join(root, "python", "site-packages"),
    ])
    existing = env.get("PYTHONPATH", "")
    merged = os.pathsep.join(
        p for p in python_paths if os.path.isdir(p) or p.endswith(".zip"))
    if existing:
        merged = merged + os.pathsep + existing if merged else existing
    if merged:
        env["PYTHONPATH"] = merged

    bin_dir = find_materialx_bin_dir()
    if bin_dir:
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    return env


def default_bakes_dir(material_name: str) -> str:
    """User documents folder for baked textures."""
    docs = os.path.join(os.path.expanduser("~"), "Documents", "Autodesk",
                        "VredX", "bakes", material_name)
    os.makedirs(docs, exist_ok=True)
    return docs
