# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""VredX install packaging helpers.

Builds the ``vredx.zip`` layout and copies the plugin into a VRED script
plugin folder.  Used by ``build.py`` and ``install.py``.
"""

import os
import re
import shutil
import zipfile

PLUGIN_NAME = "VredX"
ZIPPED_PACKAGE = "vredx"

# VRED 2027 ships as VREDPro-19.1 / Documents\VRED-19.1
VRED_2027_VERSION = "19.1"

ROOT = os.path.dirname(os.path.abspath(__file__))

INSTALL_IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", "tests", ".pytest_cache", "docs", "dist",
    "media", "scripts", "install.py", "build.py", "packaging.py",
    "_install_staging",
    ".git", ".gitignore", "CHANGELOG.md", "resources/libraries",
    "vredx.zip")


def find_scriptplugins_dir(version=VRED_2027_VERSION):
    """Per-user ScriptPlugins folder for VRED 2027 (no admin required)."""
    docs = os.path.join(os.path.expanduser("~"), "Documents", "Autodesk")
    for folder in ("VRED-%s" % version, "VREDPro-%s" % version):
        vred_dir = os.path.join(docs, folder)
        if os.path.isdir(vred_dir):
            target = os.path.join(vred_dir, "ScriptPlugins")
            os.makedirs(target, exist_ok=True)
            return target
    # VRED folder may not exist yet; create the standard 2027 path.
    target = os.path.join(docs, "VRED-%s" % version, "ScriptPlugins")
    os.makedirs(target, exist_ok=True)
    return target


def find_program_files_scripts_dir():
    """Machine-wide Program Files Scripts folder (may need elevation)."""
    autodesk = r"C:\Program Files\Autodesk"
    if not os.path.isdir(autodesk):
        return None

    def version_key(name):
        match = re.match(r"VREDPro-(\d+)\.(\d+)", name)
        return (int(match.group(1)), int(match.group(2))) if match else (0, 0)

    candidates = [d for d in os.listdir(autodesk)
                  if re.match(r"VREDPro-\d+\.\d+$", d)
                  and os.path.isdir(os.path.join(autodesk, d, "lib", "plugins",
                                                 "WIN64", "Scripts"))]
    if not candidates:
        return None
    newest = max(candidates, key=version_key)
    return os.path.join(autodesk, newest, "lib", "plugins", "WIN64", "Scripts")


def default_install_dir(use_program_files=False):
    """Default deploy target: Documents ScriptPlugins for VRED 2027."""
    if use_program_files:
        return find_program_files_scripts_dir()
    return find_scriptplugins_dir()


def zip_package(package_dir, zip_path):
    """Zip a Python package so it is importable via sys.path."""
    package_name = os.path.basename(package_dir)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for dirpath, dirnames, filenames in os.walk(package_dir):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for filename in filenames:
                if filename.endswith(".pyc"):
                    continue
                full = os.path.join(dirpath, filename)
                arcname = os.path.join(
                    package_name, os.path.relpath(full, package_dir))
                archive.write(full, arcname)


def _sanitize_plugin_target(target_root):
    """Remove loose Python files/folders VRED would load as script plugins."""
    for name in ("_install_staging", "baking"):
        path = os.path.join(target_root, name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)

    for dirpath, _dirnames, filenames in os.walk(target_root):
        for filename in filenames:
            if not filename.endswith(".py") or filename == "VredX.py":
                continue
            try:
                os.remove(os.path.join(dirpath, filename))
            except OSError:
                pass


def deploy_baking_runtime(target, source=ROOT):
    """Ship ASWF MaterialX next to VredX.py; strip it from vredx.zip."""
    materialx_src = os.path.join(
        target, ZIPPED_PACKAGE, "baking", "third_party", "materialx")
    if not os.path.isdir(materialx_src):
        materialx_src = os.path.join(
            source, ZIPPED_PACKAGE, "baking", "third_party", "materialx")
    if not os.path.isdir(materialx_src):
        return

    has_runtime = any(
        os.path.isdir(os.path.join(materialx_src, name))
        for name in ("bin", "python313", "python"))
    if not has_runtime:
        return

    dst_rt = os.path.join(target, "baking_runtime")
    dst_mx = os.path.join(dst_rt, "materialx")
    if os.path.isdir(dst_mx):
        shutil.rmtree(dst_mx)
    os.makedirs(dst_rt, exist_ok=True)
    shutil.copytree(materialx_src, dst_mx)

    pkg_mx = os.path.join(
        target, ZIPPED_PACKAGE, "baking", "third_party", "materialx")
    if os.path.isdir(pkg_mx):
        shutil.rmtree(pkg_mx)
        os.makedirs(pkg_mx, exist_ok=True)
        readme_src = os.path.join(
            source, ZIPPED_PACKAGE, "baking", "third_party",
            "materialx", "README.md")
        if os.path.isfile(readme_src):
            shutil.copy2(readme_src, os.path.join(pkg_mx, "README.md"))


def install_vredx(install_dir, source=ROOT):
    """Copy and package VredX into *install_dir* (Scripts or ScriptPlugins)."""
    target = os.path.join(install_dir, PLUGIN_NAME)
    staging = target + ".__staging__"
    if os.path.isdir(staging):
        shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(source, staging, ignore=INSTALL_IGNORE)
    deploy_baking_runtime(staging, source=source)
    package_dir = os.path.join(staging, ZIPPED_PACKAGE)
    init_py = os.path.join(package_dir, "__init__.py")
    if not os.path.isfile(init_py):
        shutil.rmtree(staging, ignore_errors=True)
        raise FileNotFoundError(
            "VredX is missing its Python package: expected %s" % init_py)
    zip_package(package_dir, package_dir + ".zip")
    shutil.rmtree(package_dir)

    if os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=True)
    try:
        os.replace(staging, target)
    except OSError:
        os.makedirs(target, exist_ok=True)
        for name in os.listdir(staging):
            src = os.path.join(staging, name)
            dst = os.path.join(target, name)
            if os.path.isdir(src):
                if os.path.isdir(dst):
                    shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(src, dst)
            else:
                try:
                    shutil.copy2(src, dst)
                except OSError:
                    pass
        shutil.rmtree(staging, ignore_errors=True)
    _sanitize_plugin_target(target)
    return target
