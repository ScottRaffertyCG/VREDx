# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""Node graphics item: rounded box with typed ports.

Nodes with many inputs (standard_surface has 42) start collapsed:
connected inputs, overridden inputs and the first few basic inputs are
shown; a small +/- toggle in the header expands the full list.
"""

from PySide6 import QtCore, QtGui, QtWidgets

from .. import style
from .port_item import INPUT, OUTPUT, PortItem

_COLLAPSED_BASIC_LIMIT = 8


class NodeItem(QtWidgets.QGraphicsItem):

    def __init__(self, node, graph):
        super().__init__()
        self.node = node          # core graph.Node
        self.graph = graph
        self.expanded = False
        self.input_ports = {}     # name -> PortItem
        self.output_ports = {}    # name -> PortItem
        self._rows = []           # [(input name, y)] for label painting
        self._height = style.NODE_HEADER_HEIGHT

        self.setFlags(
            QtWidgets.QGraphicsItem.ItemIsMovable |
            QtWidgets.QGraphicsItem.ItemIsSelectable |
            QtWidgets.QGraphicsItem.ItemSendsGeometryChanges)
        self.setPos(*node.position)
        self.rebuild_ports()

    # ------------------------------------------------------------ model info

    @property
    def node_name(self):
        return self.node.name

    def _active_compound_scope(self):
        scene = self.scene()
        if scene is None:
            return None
        return getattr(scene, "active_scope", None)

    def _export_output_names(self):
        scope = self._active_compound_scope()
        if not scope or self.node.compound != scope:
            return []
        return self.graph.compound_export_outputs(scope, self.node.name)

    def _is_compound_export_output(self):
        return bool(self._export_output_names())

    def _exported_port_names(self):
        scope = self._active_compound_scope()
        if not scope:
            return set()
        names = set()
        for output in self.graph.compounds.get(scope, ()):
            if output.internal_node == self.node.name:
                names.add(output.internal_output)
        return names

    def visible_inputs(self):
        if self.expanded:
            return [i.name for i in self.node.nodedef.inputs]
        connected = {e.dst_input for e in self.graph.edges
                     if e.dst_node == self.node.name}
        names = []
        basic_used = 0
        for idef in self.node.nodedef.inputs:
            if idef.name in connected or idef.name in self.node.values:
                names.append(idef.name)
            elif not idef.advanced and basic_used < _COLLAPSED_BASIC_LIMIT:
                names.append(idef.name)
                basic_used += 1
        return names

    # ------------------------------------------------------------- rebuild

    def rebuild_ports(self):
        self.prepareGeometryChange()
        for port in list(self.input_ports.values()) + \
                list(self.output_ports.values()):
            if port.scene() is not None:
                port.scene().removeItem(port)
            port.setParentItem(None)
        self.input_ports.clear()
        self.output_ports.clear()
        self._rows = []

        y = style.NODE_HEADER_HEIGHT + style.NODE_ROW_HEIGHT / 2.0

        for out in self.node.nodedef.outputs:
            port = PortItem(self, out.name, out.type, OUTPUT)
            port.setPos(style.NODE_WIDTH, y)
            self.output_ports[out.name] = port
            self._rows.append((out.name, y, OUTPUT))
            y += style.NODE_ROW_HEIGHT

        for name in self.visible_inputs():
            idef = self.node.nodedef.find_input(name)
            port = PortItem(self, name, idef.type, INPUT)
            port.setPos(0, y)
            self.input_ports[name] = port
            self._rows.append((name, y, INPUT))
            y += style.NODE_ROW_HEIGHT

        hidden = len(self.node.nodedef.inputs) - len(self.input_ports)
        self._hidden_count = max(0, hidden)
        if self._hidden_count and not self.expanded:
            y += style.NODE_ROW_HEIGHT * 0.8
        if self.node.is_compound:
            y += style.NODE_ROW_HEIGHT * 0.9
        elif self.node.compound and self.graph.is_compound_export_node(
                self.node.compound, self.node.name):
            y += style.NODE_ROW_HEIGHT * 0.9
        self._height = y + style.NODE_ROW_HEIGHT / 2.0

    def toggle_expanded(self):
        self.expanded = not self.expanded
        self.rebuild_ports()
        scene = self.scene()
        if scene is not None and hasattr(scene, "refresh_edges"):
            scene.refresh_edges()
        self.update()

    # ------------------------------------------------------------- geometry

    def boundingRect(self):
        return QtCore.QRectF(-2, -2, style.NODE_WIDTH + 4, self._height + 4)

    def _toggle_rect(self):
        return QtCore.QRectF(style.NODE_WIDTH - 20, 5, 14, 14)

    # ------------------------------------------------------------- painting

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = QtCore.QRectF(0, 0, style.NODE_WIDTH, self._height)

        if self.node.is_compound:
            body = style.COMPOUND_NODE_BODY
            border = (style.NODE_BORDER_SELECTED if self.isSelected()
                      else style.COMPOUND_NODE_BORDER)
            header_color = style.group_color("organization")
        elif self._is_compound_export_output():
            body = (style.EXPORT_OUTPUT_NODE_BODY if not self.isSelected()
                    else style.EXPORT_OUTPUT_NODE_BODY.lighter(125))
            border = (style.NODE_BORDER_SELECTED if self.isSelected()
                      else style.EXPORT_OUTPUT_NODE_BORDER)
            header_color = style.EXPORT_OUTPUT_HEADER
        else:
            body = style.OPAQUE_NODE_BODY if self.node.opaque else (
                style.NODE_BODY_SELECTED if self.isSelected()
                else style.NODE_BODY)
            border = (style.NODE_BORDER_SELECTED if self.isSelected()
                      else style.NODE_BORDER)
            header_color = style.group_color(self.node.nodedef.nodegroup)
        painter.setBrush(body)
        border_width = 1.8 if (self.node.is_compound
                               or self._is_compound_export_output()) else 1.4
        painter.setPen(QtGui.QPen(border, border_width))
        painter.drawRoundedRect(rect, style.NODE_RADIUS, style.NODE_RADIUS)

        # Header band tinted by nodegroup / role.
        header = QtGui.QPainterPath()
        header.addRoundedRect(
            QtCore.QRectF(0, 0, style.NODE_WIDTH, style.NODE_HEADER_HEIGHT),
            style.NODE_RADIUS, style.NODE_RADIUS)
        header.addRect(QtCore.QRectF(
            0, style.NODE_HEADER_HEIGHT / 2.0,
            style.NODE_WIDTH, style.NODE_HEADER_HEIGHT / 2.0))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(header_color)
        painter.drawPath(header.simplified())

        # Title: node name (bold) + category.
        painter.setPen(style.NODE_TEXT)
        font = painter.font()
        font.setBold(True)
        font.setPointSizeF(8.5)
        painter.setFont(font)
        title_rect = QtCore.QRectF(8, 0, style.NODE_WIDTH - 30,
                                   style.NODE_HEADER_HEIGHT)
        if self.node.is_compound:
            title = self.node.name
        elif self.node.name != self.node.category:
            title = "%s  (%s)" % (self.node.name, self.node.category)
        else:
            title = self.node.name
        painter.drawText(title_rect,
                         QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
                         painter.fontMetrics().elidedText(
                             title, QtCore.Qt.ElideRight,
                             int(title_rect.width())))

        # Expand toggle (not for compound group nodes).
        if self.node.nodedef.inputs and not self.node.is_compound:
            painter.setPen(QtGui.QPen(style.NODE_TEXT, 1.2))
            trect = self._toggle_rect()
            cy = trect.center().y()
            painter.drawLine(QtCore.QPointF(trect.left() + 3, cy),
                             QtCore.QPointF(trect.right() - 3, cy))
            if not self.expanded:
                cx = trect.center().x()
                painter.drawLine(QtCore.QPointF(cx, trect.top() + 3),
                                 QtCore.QPointF(cx, trect.bottom() - 3))

        # Port labels.
        font.setBold(False)
        font.setPointSizeF(7.5)
        painter.setFont(font)
        for name, y, direction in self._rows:
            row = QtCore.QRectF(12, y - style.NODE_ROW_HEIGHT / 2.0,
                                style.NODE_WIDTH - 24, style.NODE_ROW_HEIGHT)
            exported_ports = self._exported_port_names()
            if direction == OUTPUT:
                painter.setPen(style.EXPORT_OUTPUT_NODE_BORDER
                               if name in exported_ports
                               else style.NODE_SUBTEXT)
                painter.drawText(row, QtCore.Qt.AlignVCenter |
                                 QtCore.Qt.AlignRight, name)
            else:
                overridden = name in self.node.values
                painter.setPen(style.NODE_TEXT if overridden
                               else style.NODE_SUBTEXT)
                painter.drawText(
                    row, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
                    painter.fontMetrics().elidedText(
                        name, QtCore.Qt.ElideRight, int(row.width())))

        # Hidden-input hint.
        if self._hidden_count and not self.expanded:
            painter.setPen(style.NODE_SUBTEXT)
            hint_rect = QtCore.QRectF(
                12, self._height - style.NODE_ROW_HEIGHT * 1.2,
                style.NODE_WIDTH - 24, style.NODE_ROW_HEIGHT)
            painter.drawText(hint_rect,
                             QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
                             "+ %d more..." % self._hidden_count)
        elif self.node.is_compound:
            count = self.graph.compound_member_count(self.node.name)
            painter.setPen(style.NODE_SUBTEXT)
            hint_rect = QtCore.QRectF(
                12, self._height - style.NODE_ROW_HEIGHT * 1.1,
                style.NODE_WIDTH - 24, style.NODE_ROW_HEIGHT)
            hint = "%d node(s)  ·  double-click to open" % count
            painter.drawText(hint_rect,
                             QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
                             painter.fontMetrics().elidedText(
                                 hint, QtCore.Qt.ElideRight,
                                 int(hint_rect.width())))
        elif self._is_compound_export_output():
            painter.setPen(style.EXPORT_OUTPUT_NODE_BORDER)
            hint_rect = QtCore.QRectF(
                12, self._height - style.NODE_ROW_HEIGHT * 1.1,
                style.NODE_WIDTH - 24, style.NODE_ROW_HEIGHT)
            labels = ", ".join(self._export_output_names())
            hint = "graph output: %s" % labels
            painter.drawText(hint_rect,
                             QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
                             painter.fontMetrics().elidedText(
                                 hint, QtCore.Qt.ElideRight,
                                 int(hint_rect.width())))

    # ---------------------------------------------------------- interaction

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and \
                self._toggle_rect().contains(event.pos()):
            self.toggle_expanded()
            event.accept()
            return
        super().mousePressEvent(event)

    def itemChange(self, change, value):
        if change == QtWidgets.QGraphicsItem.ItemPositionHasChanged:
            scene = self.scene()
            if scene is not None and hasattr(scene, "refresh_edges"):
                scene.refresh_edges()
        return super().itemChange(change, value)
