# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""VredX - MaterialX authoring plugin for Autodesk VRED.

Entry point loaded by VRED's script-plugin mechanism.  Ship as ``VredX.py`` plus
``vredx.zip`` (zip the ``vredx/`` package; do not leave loose ``vredx/*.py`` in
ScriptPlugins — VRED's scanner executes every loose ``.py`` file it finds).

Integration:
 * dockable panel via VREDPluginWidget (Scripts menu) or QDockWidget,
 * top-level "VREDX" menu in the VRED menu bar,
 * floating window via Pop Out Editor.

The menu is installed at load; the editor opens on demand.
"""

import importlib
import os
import sys

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))

_PKG_ZIP = os.path.join(_PLUGIN_DIR, "vredx.zip")
if os.path.isdir(os.path.join(_PLUGIN_DIR, "vredx")):
    _PKG_PATH = _PLUGIN_DIR
elif os.path.isfile(_PKG_ZIP):
    _PKG_PATH = _PKG_ZIP
else:
    raise ImportError("VredX: neither vredx/ nor vredx.zip found in %s"
                      % _PLUGIN_DIR)
if _PKG_PATH not in sys.path:
    sys.path.insert(0, _PKG_PATH)

importlib.invalidate_caches()
_vredx_modules = sorted(
    (n for n in list(sys.modules) if n == "vredx" or n.startswith("vredx.")),
    key=lambda name: name.count("."),
    reverse=True)
for _name in _vredx_modules:
    sys.modules.pop(_name, None)
import vredx                                                    # noqa: E402

from PySide6 import QtCore, QtWidgets                                   # noqa: E402

from vredx.core.nodedef_library import NodeDefLibrary           # noqa: E402
from vredx.ui import style                                      # noqa: E402
from vredx.ui.main_window import VredXWindow                    # noqa: E402
from vredx.vredbridge import ui_integration                    # noqa: E402
from vredx.baking.runtime import is_runtime_available          # noqa: E402


def _qt_alive(obj):
    if obj is None:
        return False
    try:
        obj.objectName()
        return True
    except RuntimeError:
        return False


class VredXPlugin:
    """Plugin lifecycle: window + VREDX menu."""

    def __init__(self, parent_widget):
        self._library = None
        self.window = VredXWindow(
            None, None, library_loader=self._load_library)
        self.window.hide()

        if parent_widget is not None and parent_widget.layout() is not None:
            self.window._docked_parent = parent_widget
            self.window._docked_layout = parent_widget.layout()
            parent_widget.layout().addWidget(self.window)
            try:
                parent_widget.setWindowTitle("VREDX")
                parent_widget.setWindowIcon(style.vredx_icon())
                flags = parent_widget.windowFlags()
                flags |= (QtCore.Qt.WindowMinimizeButtonHint
                          | QtCore.Qt.WindowMaximizeButtonHint)
                parent_widget.setWindowFlags(flags)
            except (AttributeError, RuntimeError):
                pass

        self.menu = ui_integration.VredXMenu()
        menu_callbacks = {
            "open_editor": self.show_editor,
            "pop_out_editor": self.pop_out_editor,
            "new_material": self.new_material,
            "import_mtlx": self.import_mtlx,
            "about": self.show_about,
        }
        if is_runtime_available():
            menu_callbacks["bake_textures"] = self.show_baking
        self.menu.install(menu_callbacks)

    def _load_library(self):
        if self._library is None:
            self._library = NodeDefLibrary.load()
        return self._library

    @property
    def library(self):
        return self._load_library()

    def show_editor(self):
        window = self.window
        if not _qt_alive(window):
            return
        window.ensure_editor_ready()
        window.ensure_docked_and_show()

    def pop_out_editor(self):
        window = self.window
        if not _qt_alive(window):
            return
        window.ensure_editor_ready()
        window._pop_out_editor()

    def new_material(self):
        self.show_editor()
        self.window.new_document()

    def import_mtlx(self):
        self.show_editor()
        self.window.open_dialog()

    def show_baking(self):
        if not is_runtime_available():
            return
        self.show_editor()
        self.window.show_baking_panel()

    def show_about(self):
        import vredx
        parent = self.window
        if not _qt_alive(parent):
            parent = None
        QtWidgets.QMessageBox.about(
            parent, "About VredX",
            "<b>VredX %s</b><br>MaterialX authoring for Autodesk VRED.<br>"
            "Node palette from:<br><code>%s</code><br><br>"
            "Texture baking powered by "
            "<a href=\"https://github.com/AcademySoftwareFoundation/MaterialX\">"
            "ASWF MaterialX</a> (Apache 2.0)."
            % (vredx.__version__,
               self.library.source_root or ""))

    def shutdown(self):
        self.menu.remove()
        if _qt_alive(self.window):
            dock = getattr(self.window, "_vred_dock", None)
            if _qt_alive(dock):
                try:
                    dock.setWidget(None)
                    dock.close()
                    dock.deleteLater()
                except RuntimeError:
                    pass
            self.window.shutdown()


try:
    _parent = VREDPluginWidget
except NameError:
    _parent = None

vredXPlugin = VredXPlugin(_parent)


def onDestroyVREDScriptPlugin():
    """Called by VRED before the plugin is destroyed or reloaded."""
    vredXPlugin.shutdown()
