# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""Node graph view: zooming, panning, keyboard shortcuts, quick-add."""

from PySide6 import QtCore, QtGui, QtWidgets

from .scene import NodeGraphScene

ZOOM_MIN = 0.15
ZOOM_MAX = 3.0


class NodeGraphView(QtWidgets.QGraphicsView):

    def __init__(self, scene: NodeGraphScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QtGui.QPainter.Antialiasing |
                            QtGui.QPainter.TextAntialiasing)
        self.setDragMode(QtWidgets.QGraphicsView.RubberBandDrag)
        self.setRubberBandSelectionMode(
            QtCore.Qt.ItemSelectionMode.IntersectsItemShape)
        self.setTransformationAnchor(
            QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setAcceptDrops(True)
        self._panning = False
        self._pan_start = QtCore.QPoint()
        self._connecting = False
        self._initial_fit_done = False

    def graph_scene(self) -> NodeGraphScene:
        return self.scene()

    # ---------------------------------------------------------------- zoom

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self._zoom_by(factor)
        event.accept()

    def _zoom_by(self, factor):
        """Scale the view, clamping into [ZOOM_MIN, ZOOM_MAX].

        Clamping (instead of refusing out-of-range steps) matters: if an
        early fitInView ever leaves the view below ZOOM_MIN, a refusing
        check would lock zooming permanently.
        """
        current = self.transform().m11()
        target = max(ZOOM_MIN, min(ZOOM_MAX, current * factor))
        if abs(target - current) > 1e-9:
            step = target / current
            self.scale(step, step)

    def fit_all(self):
        scene = self.graph_scene()
        items = list(scene.node_items.values())
        if scene._output_panel is not None:
            items.append(scene._output_panel)
        if not items:
            return
        rect = QtCore.QRectF()
        for item in items:
            rect = rect.united(item.sceneBoundingRect())
        self.fitInView(rect.adjusted(-60, -60, 60, 60),
                       QtCore.Qt.KeepAspectRatio)
        # Keep the resulting scale inside the interactive zoom range so
        # the wheel always has room to move (1.0 max: never zoom past
        # 100% just because the graph is small).
        scale = self.transform().m11()
        clamped = max(ZOOM_MIN, min(1.0, scale))
        if abs(scale - clamped) > 1e-9 and scale > 0:
            self.setTransform(QtGui.QTransform.fromScale(clamped, clamped))
            self.centerOn(rect.center())

    def showEvent(self, event):
        super().showEvent(event)
        # The window constructs (and fits) before layout has real sizes;
        # redo the initial fit once the viewport actually exists.
        if not self._initial_fit_done:
            self._initial_fit_done = True
            QtCore.QTimer.singleShot(0, self.fit_all)

    # ----------------------------------------------------------------- pan

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MiddleButton or (
                event.button() == QtCore.Qt.LeftButton and
                event.modifiers() & QtCore.Qt.AltModifier):
            self._panning = True
            self._pan_start = event.position().toPoint()
            self.setCursor(QtCore.Qt.ClosedHandCursor)
            event.accept()
            return
        if event.button() == QtCore.Qt.LeftButton:
            port = self._port_at_view_pos(event.position().toPoint())
            if port is not None:
                scene = self.graph_scene()
                if scene.begin_connection(port):
                    self._connecting = True
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            delta = event.position().toPoint() - self._pan_start
            self._pan_start = event.position().toPoint()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        scene = self.graph_scene()
        if self._connecting or scene._drag_edge is not None:
            scene.update_connection_drag(
                self.mapToScene(event.position().toPoint()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning and event.button() in (
                QtCore.Qt.MiddleButton, QtCore.Qt.LeftButton):
            self._panning = False
            self.setCursor(QtCore.Qt.ArrowCursor)
            event.accept()
            return
        scene = self.graph_scene()
        if event.button() == QtCore.Qt.LeftButton and (
                self._connecting or scene._drag_edge is not None):
            scene.finish_connection_drag(
                self.mapToScene(event.position().toPoint()))
            self._connecting = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------ keyboard

    def keyPressEvent(self, event):
        scene = self.graph_scene()
        key = event.key()
        mods = event.modifiers()
        if key in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
            scene.delete_selected()
        elif key == QtCore.Qt.Key_D and mods & QtCore.Qt.ControlModifier:
            scene.duplicate_selected()
        elif key == QtCore.Qt.Key_Z and mods & QtCore.Qt.ControlModifier:
            if mods & QtCore.Qt.ShiftModifier:
                scene.stack.redo()
            else:
                scene.stack.undo()
        elif key == QtCore.Qt.Key_Y and mods & QtCore.Qt.ControlModifier:
            scene.stack.redo()
        elif key == QtCore.Qt.Key_F:
            self.fit_all()
        elif key == QtCore.Qt.Key_Tab:
            self.show_quick_add()
        elif key == QtCore.Qt.Key_Escape:
            scene.cancel_connection_drag()
            self._connecting = False
        else:
            super().keyPressEvent(event)

    # ----------------------------------------------------------- quick add

    def contextMenuEvent(self, event):
        self.show_quick_add(event.globalPos(),
                            self.mapToScene(event.pos()))

    def _port_at_view_pos(self, view_pos):
        return self.graph_scene()._port_at(
            self.mapToScene(view_pos))

    def show_quick_add(self, global_pos=None, scene_pos=None):
        if global_pos is None:
            global_pos = QtGui.QCursor.pos()
        if scene_pos is None:
            scene_pos = self.mapToScene(
                self.mapFromGlobal(global_pos))
        dialog = QuickAddDialog(self.graph_scene().library, self)
        dialog.move(global_pos)
        if dialog.exec() == QtWidgets.QDialog.Accepted and dialog.chosen:
            self.graph_scene().add_node_at(dialog.chosen, scene_pos)


class QuickAddDialog(QtWidgets.QDialog):
    """Tab-style fuzzy search popup for adding nodes."""

    def __init__(self, library, parent=None):
        super().__init__(parent, QtCore.Qt.Popup)
        self.library = library
        self.chosen = None
        self.setObjectName("VredXRoot")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.edit = QtWidgets.QLineEdit(self)
        self.edit.setPlaceholderText("Add node...")
        self.list = QtWidgets.QListWidget(self)
        self.list.setMinimumSize(260, 280)
        layout.addWidget(self.edit)
        layout.addWidget(self.list)

        self.edit.textChanged.connect(self._refilter)
        self.edit.returnPressed.connect(self._accept_current)
        self.list.itemActivated.connect(lambda _i: self._accept_current())
        self.edit.installEventFilter(self)
        self._refilter("")
        self.edit.setFocus()

    def _refilter(self, text):
        text = text.lower().strip()
        self.list.clear()
        for node_name in self.library.node_names():
            all_variants = self.library.variants(node_name)
            if text:
                if text in node_name.lower():
                    variants = all_variants
                else:
                    variants = [nd for nd in all_variants
                                if nd.matches_filter(text, node_name)]
            else:
                variants = all_variants
            if not variants:
                continue
            for nd in variants:
                item = QtWidgets.QListWidgetItem(
                    "%s  (%s)" % (node_name, nd.type_signature()))
                item.setData(QtCore.Qt.UserRole, nd.name)
                item.setToolTip(nd.palette_tooltip())
                self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _accept_current(self):
        item = self.list.currentItem()
        if item is None:
            return
        self.chosen = self.library.get(item.data(QtCore.Qt.UserRole))
        self.accept()

    def eventFilter(self, obj, event):
        if obj is self.edit and event.type() == QtCore.QEvent.KeyPress:
            if event.key() in (QtCore.Qt.Key_Down, QtCore.Qt.Key_Up):
                row = self.list.currentRow()
                row += 1 if event.key() == QtCore.Qt.Key_Down else -1
                row = max(0, min(self.list.count() - 1, row))
                self.list.setCurrentRow(row)
                return True
        return super().eventFilter(obj, event)
