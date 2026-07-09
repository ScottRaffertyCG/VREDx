# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""VRED main-window integration: the top-level "VREDX" menu.

VRED exposes its Qt main window to Python (``getMainWindow()`` /
``vredMainWindow`` are injected at startup); we wrap it with shiboken6
and insert a QMenu into the menu bar.  Everything is guarded so the
module also imports outside VRED (menu installation is skipped).
"""

from PySide6 import QtWidgets

MENU_TITLE = "VREDX"


def vred_main_window():
    """The VRED QMainWindow, or None outside VRED."""
    import builtins
    # Preferred: pointer from getMainWindow() wrapped via shiboken6.
    get_main_window = getattr(builtins, "getMainWindow", None)
    if get_main_window is not None:
        try:
            from shiboken6 import wrapInstance
            pointer = get_main_window()
            return wrapInstance(int(pointer), QtWidgets.QMainWindow)
        except (RuntimeError, TypeError, ValueError):
            pass
    for name in ("vredMainWindow", "vrMainWindow"):
        window = getattr(builtins, name, None)
        if isinstance(window, QtWidgets.QMainWindow):
            return window
        if callable(window):
            try:
                result = window()
                if isinstance(result, QtWidgets.QMainWindow):
                    return result
            except (RuntimeError, TypeError, ValueError):
                pass
    return None


class VredXMenu:
    """Owns the VREDX menu; call remove() before plugin unload."""

    def __init__(self):
        self.menu = None
        self._main_window = None

    def install(self, callbacks):
        """callbacks: dict with open_editor / new_material / import_mtlx /
        about callables (missing keys are skipped)."""
        window = vred_main_window()
        if window is None:
            return False
        self.remove()
        self._main_window = window
        menubar = window.menuBar()

        self.menu = QtWidgets.QMenu(MENU_TITLE, menubar)
        self.menu.setObjectName("VredXMenu")

        entries = [
            ("Open MaterialX Editor", "open_editor"),
            ("Pop Out Editor", "pop_out_editor"),
            ("New Material", "new_material"),
            ("Import .mtlx...", "import_mtlx"),
            ("Bake Textures…", "bake_textures"),
            (None, None),
            ("About VredX", "about"),
        ]
        for label, key in entries:
            if label is None:
                self.menu.addSeparator()
                continue
            callback = callbacks.get(key)
            if callback is None:
                continue
            action = self.menu.addAction(label)
            action.triggered.connect(
                lambda checked=False, cb=callback: cb())

        # Insert before the Help menu when present, else append.
        help_action = None
        for action in menubar.actions():
            if action.text().replace("&", "").strip().lower() == "help":
                help_action = action
                break
        if help_action is not None:
            menubar.insertMenu(help_action, self.menu)
        else:
            menubar.addMenu(self.menu)
        return True

    def remove(self):
        if self.menu is not None:
            try:
                self.menu.menuAction().setVisible(False)
                if self._main_window is not None:
                    self._main_window.menuBar().removeAction(
                        self.menu.menuAction())
                self.menu.deleteLater()
            except (RuntimeError, TypeError, ValueError, AttributeError):
                pass
            self.menu = None
            self._main_window = None
