# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""Output boundary panel shown inside a nested nodegraph scope."""

from PySide6 import QtCore, QtGui, QtWidgets

from .. import style
from .port_item import INPUT, PortItem


class CompoundOutputPanelItem(QtWidgets.QGraphicsItem):
    """Selectable panel listing the compound nodegraph's exported outputs."""

    PANEL_WIDTH = 170

    def __init__(self, compound_name: str, outputs):
        super().__init__()
        self.compound_name = compound_name
        self.outputs = list(outputs)
        self.input_ports = {}     # output name -> PortItem
        self._rows = []
        self._height = style.NODE_HEADER_HEIGHT
        self.setFlags(
            QtWidgets.QGraphicsItem.ItemIsMovable |
            QtWidgets.QGraphicsItem.ItemIsSelectable |
            QtWidgets.QGraphicsItem.ItemSendsGeometryChanges)
        self.setZValue(0)
        self.rebuild_ports()

    @property
    def node_name(self):
        return "__outputs__"

    def rebuild_ports(self):
        self.prepareGeometryChange()
        for port in self.input_ports.values():
            if port.scene() is not None:
                port.scene().removeItem(port)
            port.setParentItem(None)
        self.input_ports.clear()
        self._rows = []

        y = style.NODE_HEADER_HEIGHT + style.NODE_ROW_HEIGHT / 2.0
        for output in self.outputs:
            port = PortItem(self, output.name, output.type, INPUT)
            port.setPos(0, y)
            port.setAcceptedMouseButtons(QtCore.Qt.NoButton)
            port.setToolTip(
                "Exported as %s on %s" % (output.name, self.compound_name))
            self.input_ports[output.name] = port
            self._rows.append((output.name, y))
            y += style.NODE_ROW_HEIGHT
        self._height = y + style.NODE_ROW_HEIGHT / 2.0

    def boundingRect(self):
        return QtCore.QRectF(-2, -2, self.PANEL_WIDTH + 4, self._height + 4)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = QtCore.QRectF(0, 0, self.PANEL_WIDTH, self._height)

        body = (style.COMPOUND_NODE_BODY if not self.isSelected()
                else style.COMPOUND_NODE_BODY.lighter(120))
        border = (style.NODE_BORDER_SELECTED if self.isSelected()
                  else style.COMPOUND_NODE_BORDER)
        painter.setBrush(body)
        painter.setPen(QtGui.QPen(border, 1.6))
        painter.drawRoundedRect(rect, style.NODE_RADIUS, style.NODE_RADIUS)

        header = QtGui.QPainterPath()
        header.addRoundedRect(
            QtCore.QRectF(0, 0, self.PANEL_WIDTH, style.NODE_HEADER_HEIGHT),
            style.NODE_RADIUS, style.NODE_RADIUS)
        header.addRect(QtCore.QRectF(
            0, style.NODE_HEADER_HEIGHT / 2.0,
            self.PANEL_WIDTH, style.NODE_HEADER_HEIGHT / 2.0))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(style.group_color("organization"))
        painter.drawPath(header.simplified())

        painter.setPen(style.NODE_TEXT)
        font = painter.font()
        font.setBold(True)
        font.setPointSizeF(8.5)
        painter.setFont(font)
        title_rect = QtCore.QRectF(
            8, 0, self.PANEL_WIDTH - 16, style.NODE_HEADER_HEIGHT)
        painter.drawText(title_rect,
                         QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
                         "Graph outputs")

        font.setBold(False)
        font.setPointSizeF(7.5)
        painter.setFont(font)
        for name, y in self._rows:
            row = QtCore.QRectF(
                12, y - style.NODE_ROW_HEIGHT / 2.0,
                self.PANEL_WIDTH - 24, style.NODE_ROW_HEIGHT)
            painter.setPen(style.NODE_SUBTEXT)
            painter.drawText(
                row, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
                painter.fontMetrics().elidedText(
                    name, QtCore.Qt.ElideRight, int(row.width())))

    def itemChange(self, change, value):
        if change == QtWidgets.QGraphicsItem.ItemPositionHasChanged:
            scene = self.scene()
            if scene is not None and hasattr(scene, "refresh_edges"):
                scene.refresh_edges()
        return super().itemChange(change, value)
