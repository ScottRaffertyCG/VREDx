# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""VredX - MaterialX authoring plugin for Autodesk VRED 2027.

Package layout:
    vredx.core        UI-free document model, MaterialX I/O, validation
    vredx.ui          PySide6 node-graph editor
    vredx.vredbridge  VRED integration (guarded imports, safe outside VRED)

When installed, this package is shipped as ``vredx.zip`` (see
install.py): VRED's script-plugin scanner executes every loose .py file
it finds, which would run all library modules standalone at startup.
Zip-imported modules are invisible to the scanner.
"""

import os

__version__ = "0.6.0"


def plugin_root() -> str:
    """The VredX plugin folder holding resources/, presets/, docs/.

    Works both for a source checkout (…/VredX/vredx/__init__.py) and a
    packaged install (…/VredX/vredx.zip/vredx/__init__.py), where the
    on-disk data folders live next to the zip, not inside it.
    """
    root = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), ".."))
    if root.lower().endswith(".zip"):
        root = os.path.dirname(root)
    return root
