# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""VRED main-window integration: the top-level "VREDX" menu.

VRED exposes its Qt main window to Python (``getMainWindow()`` /
``vredMainWindow`` are injected at startup); we wrap it with shiboken6
and insert a QMenu into the menu bar.  Everything is guarded so the
module also imports outside VRED (menu installation is skipped).
"""

from PySide6 import QtCore, QtWidgets

MENU_TITLE = "VREDX"
DOCK_OBJECT_NAME = "VredXDock"
DEFAULT_DOCK_WIDTH = 420
MIN_DOCK_WIDTH = 280
MIN_DOCK_HEIGHT = 200


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


def find_vredx_dock(main_window=None):
    """Return an existing VREDX QDockWidget, or None."""
    main_window = main_window or vred_main_window()
    if main_window is None:
        return None
    for dock in main_window.findChildren(QtWidgets.QDockWidget):
        if dock.objectName() == DOCK_OBJECT_NAME:
            return dock
    return None


def _dock_features():
    return (
        QtWidgets.QDockWidget.DockWidgetMovable
        | QtWidgets.QDockWidget.DockWidgetFloatable
        | QtWidgets.QDockWidget.DockWidgetClosable
    )


def ensure_vredx_dock(main_window=None):
    """Create or reuse the VREDX dock on VRED's main window."""
    main_window = main_window or vred_main_window()
    if main_window is None:
        return None
    dock = find_vredx_dock(main_window)
    if dock is not None:
        restore_dock(dock, main_window)
        return dock
    dock = QtWidgets.QDockWidget("VREDX", main_window)
    dock.setObjectName(DOCK_OBJECT_NAME)
    dock.setAllowedAreas(
        QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea
        | QtCore.Qt.BottomDockWidgetArea | QtCore.Qt.TopDockWidgetArea
    )
    dock.setFeatures(_dock_features())
    dock.setMinimumWidth(MIN_DOCK_WIDTH)
    main_window.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    return dock


def restore_dock(dock, main_window=None):
    """Reattach the dock and restore its title bar / features."""
    if dock is None:
        return
    main_window = main_window or vred_main_window()
    try:
        dock.setTitleBarWidget(None)
        dock.setWindowTitle("VREDX")
        dock.setFeatures(_dock_features())
        if dock.isFloating():
            dock.setFloating(False)
        if main_window is not None and dock.parentWidget() is not main_window:
            main_window.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    except RuntimeError:
        pass


def apply_default_dock_width(dock, main_window=None):
    """Clamp an oversized dock to a reasonable default width."""
    main_window = main_window or vred_main_window()
    if main_window is None or dock is None:
        return
    try:
        current = dock.width()
    except RuntimeError:
        return
    target = min(
        DEFAULT_DOCK_WIDTH,
        max(MIN_DOCK_WIDTH, int(main_window.width() * 0.35)),
    )
    if current <= 0 or current > target + 40:
        main_window.resizeDocks(
            [dock], [target], QtCore.Qt.Horizontal)


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
