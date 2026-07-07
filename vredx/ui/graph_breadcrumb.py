# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""Breadcrumb bar for nested nodegraph navigation."""

from typing import List, Optional, Tuple

from PySide6 import QtCore, QtWidgets


class GraphBreadcrumb(QtWidgets.QWidget):
    """Clickable path: Root > NG_Car_Paint > ..."""

    navigated = QtCore.Signal(object)  # None = root, str = compound name

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VredXGraphBreadcrumb")
        self._layout = QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(6, 2, 6, 2)
        self._layout.setSpacing(4)
        self._segments: List[Tuple[str, Optional[str]]] = []
        self._base_stylesheet = """
            #VredXGraphBreadcrumb {
                background: #2a2a2e;
                border: 1px solid #1a1a1c;
                border-radius: 4px;
            }
            #VredXGraphBreadcrumb QPushButton {
                background: transparent;
                border: none;
                color: #c8c8cc;
                padding: 2px 4px;
            }
            #VredXGraphBreadcrumb QPushButton:hover {
                color: #ffffff;
                text-decoration: underline;
            }
            #VredXGraphBreadcrumb QPushButton:disabled {
                color: #ffffff;
                font-weight: 600;
            }
            #VredXGraphBreadcrumb QLabel {
                color: #6a6a70;
            }
        """
        self.setStyleSheet(self._base_stylesheet)

    def sync_font_from_menubar(self, menubar):
        """Match breadcrumb text to the main menu bar."""
        if menubar is None:
            return
        font = menubar.font()
        self.setFont(font)
        size = font.pointSize()
        if size <= 0:
            size = max(12, int(round(font.pointSizeF() * 1.33)))
        self.setStyleSheet(self._base_stylesheet + (
            "\n#VredXGraphBreadcrumb QPushButton, "
            "#VredXGraphBreadcrumb QLabel { font-size: %dpt; }" % size))

    def set_path(self, segments: List[Tuple[str, Optional[str]]]):
        """Update crumbs.

        Each segment is ``(label, scope)`` where *scope* is ``None`` for
        the document root or a compound nodegraph name.
        """
        self._segments = list(segments)
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for index, (label, scope) in enumerate(segments):
            if index:
                sep = QtWidgets.QLabel("›", self)
                self._layout.addWidget(sep)
            button = QtWidgets.QPushButton(label, self)
            is_current = index == len(segments) - 1
            button.setEnabled(not is_current)
            button.setFlat(True)
            button.clicked.connect(
                lambda checked=False, i=index: self._on_click(i))
            self._layout.addWidget(button)
        self._layout.addStretch(1)
        self.setVisible(len(segments) > 1)

    def _on_click(self, index: int):
        if index < 0 or index >= len(self._segments):
            return
        _label, scope = self._segments[index]
        self.navigated.emit(scope)
