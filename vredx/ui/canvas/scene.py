# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""Node graph scene: keeps graphics items in sync with the core Graph.

The core model is the single source of truth.  All mutations go through
the CommandStack; after every command the scene re-syncs its items.
Interactive behaviors implemented here:

* connection dragging from ports (with type-aware highlighting),
* picking up an existing connection from its input end,
* palette drag-and-drop node creation,
* undoable node moves.
"""

from PySide6 import QtCore, QtGui, QtWidgets

from ...core import commands
from ...core.graph import Graph
from .. import style
from .compound_output_panel import CompoundOutputPanelItem
from .edge_item import DragEdgeItem, EdgeItem
from .node_item import NodeItem
from .port_item import INPUT, OUTPUT, PortItem

NODEDEF_MIME = "application/x-vredx-nodedef"


class NodeGraphScene(QtWidgets.QGraphicsScene):

    graph_changed = QtCore.Signal()
    node_double_clicked = QtCore.Signal(str)

    def __init__(self, graph: Graph, stack: commands.CommandStack,
                 library, parent=None):
        super().__init__(parent)
        self.graph = graph
        self.stack = stack
        self.library = library
        self.node_items = {}      # name -> NodeItem
        self.edge_items = []      # [EdgeItem]
        self._output_panel = None
        self._output_edge_items = []
        self._output_panel_positions = {}   # compound scope -> (x, y)

        self._drag_edge = None
        self._drag_port = None
        self._pending_pickup = None   # existing core Edge being re-routed
        self._snap_target = None      # locked compatible port during drag
        self._move_start = {}         # name -> (x, y) at mouse press
        self._output_panel_move_start = None
        self.active_scope = None      # None = document root

        self.setSceneRect(-5000, -5000, 10000, 10000)
        self.setBackgroundBrush(style.CANVAS_BG)
        self.stack.changed_callbacks.append(self._on_stack_changed)

    # ------------------------------------------------------------ document

    def set_graph(self, graph: Graph):
        self.graph = graph
        self.active_scope = None
        self._output_panel_positions = {}
        self.stack.clear()
        self.sync()

    def set_active_scope(self, scope):
        """Switch the visible nodegraph scope (None = document root)."""
        self.active_scope = scope
        self.sync()

    def _on_stack_changed(self):
        self.sync()
        self.graph_changed.emit()

    # ---------------------------------------------------------------- sync

    def sync(self):
        """Rebuild items to match the model, preserving selection."""
        selected = {i.node_name for i in self.selectedItems()
                    if isinstance(i, NodeItem)}
        visible = set(self.graph.nodes_in_scope(self.active_scope))

        for name in list(self.node_items):
            if name not in visible:
                item = self.node_items.pop(name)
                self.removeItem(item)
        for name in visible:
            node = self.graph.nodes[name]
            item = self.node_items.get(name)
            if item is None or item.node is not node:
                if item is not None:
                    self.removeItem(item)
                item = NodeItem(node, self.graph)
                self.node_items[name] = item
                self.addItem(item)
            else:
                if (item.pos().x(), item.pos().y()) != node.position:
                    item.setPos(*node.position)
            item.rebuild_ports()

        self._sync_output_panel()
        self._rebuild_edges()

        for name in selected:
            if name in self.node_items:
                item = self.node_items[name]
                if not item.isSelected():
                    item.setSelected(True)
        self.update()

    def _sync_output_panel(self):
        """Show exported output ports when viewing inside a compound."""
        scope = self.active_scope
        if self._output_panel is not None:
            pos = self._output_panel.pos()
            self._output_panel_positions[self._output_panel.compound_name] = (
                pos.x(), pos.y())
            self.removeItem(self._output_panel)
            self._output_panel = None

        if not scope:
            return
        outputs = self.graph.compounds.get(scope)
        if not outputs:
            return

        self._output_panel = CompoundOutputPanelItem(scope, outputs)
        self.addItem(self._output_panel)
        if scope in self._output_panel_positions:
            self._output_panel.setPos(*self._output_panel_positions[scope])
        else:
            self._output_panel.setPos(*self._initial_output_panel_pos())
            self._output_panel_positions[scope] = (
                self._output_panel.pos().x(), self._output_panel.pos().y())

    def _initial_output_panel_pos(self):
        """Default placement when first entering a compound scope."""
        items = list(self.node_items.values())
        if not items:
            return (220.0, 0.0)
        max_x = max(item.pos().x() + style.NODE_WIDTH for item in items)
        min_y = min(item.pos().y() for item in items)
        return (max_x + 80.0, min_y)

    def _rebuild_edges(self):
        for item in self.edge_items:
            if item.scene() is not None:
                self.removeItem(item)
        self.edge_items = []
        for item in self._output_edge_items:
            if item.scene() is not None:
                self.removeItem(item)
        self._output_edge_items = []
        for edge in self.graph.edges:
            if not self.graph.edge_in_scope(edge, self.active_scope):
                continue
            src_item = self.node_items.get(edge.src_node)
            dst_item = self.node_items.get(edge.dst_node)
            if src_item is None or dst_item is None:
                continue
            src_port = src_item.output_ports.get(edge.src_output)
            dst_port = dst_item.input_ports.get(edge.dst_input)
            if src_port is None or dst_port is None:
                continue
            item = EdgeItem(edge, src_port, dst_port)
            self.edge_items.append(item)
            self.addItem(item)
        self._rebuild_output_edges()

    def _rebuild_output_edges(self):
        """Wire internal nodes to the compound's exported output panel."""
        if self._output_panel is None or not self.active_scope:
            return
        outputs = self.graph.compounds.get(self.active_scope, ())
        for output in outputs:
            src_item = self.node_items.get(output.internal_node)
            if src_item is None:
                continue
            src_port = src_item.output_ports.get(output.internal_output)
            if src_port is None and src_item.output_ports:
                src_port = next(iter(src_item.output_ports.values()))
            dst_port = self._output_panel.input_ports.get(output.name)
            if src_port is None or dst_port is None:
                continue
            item = EdgeItem(None, src_port, dst_port)
            self._output_edge_items.append(item)
            self.addItem(item)

    def refresh_edges(self):
        for item in self.edge_items:
            item.refresh()
        for item in self._output_edge_items:
            item.refresh()

    # ----------------------------------------------------------- edit ops

    def add_node_at(self, nodedef, pos: QtCore.QPointF):
        cmd = commands.AddNodeCommand(
            self.graph, nodedef, position=(pos.x(), pos.y()),
            compound=self.active_scope)
        self.stack.push(cmd)
        return cmd.node

    def delete_selected(self):
        names = [i.node_name for i in self.selectedItems()
                 if isinstance(i, NodeItem)]
        edges = [i.edge for i in self.selectedItems()
                 if isinstance(i, EdgeItem) and i.edge is not None
                 and i.edge.src_node not in names
                 and i.edge.dst_node not in names]
        for edge in edges:
            self.stack.push(commands.DisconnectCommand(self.graph, edge))
        if names:
            self.stack.push(commands.RemoveNodesCommand(self.graph, names))

    def duplicate_selected(self):
        items = [i for i in self.selectedItems() if isinstance(i, NodeItem)]
        new_names = []
        for item in items:
            node = item.node
            cmd = commands.AddNodeCommand(
                self.graph, node.nodedef, name=node.name,
                position=(node.position[0] + 40, node.position[1] + 40))
            self.stack.push(cmd)
            cmd.node.values.update(node.values)
            cmd.node.expose_in_material = node.expose_in_material
            new_names.append(cmd.node.name)
        self.clearSelection()
        for name in new_names:
            if name in self.node_items:
                self.node_items[name].setSelected(True)

    def selected_node_names(self):
        return [i.node_name for i in self.selectedItems()
                if isinstance(i, NodeItem)]

    # ------------------------------------------------------ connection drag

    def host_view(self):
        """The primary view displaying this scene, if any."""
        views = self.views()
        return views[0] if views else None

    def begin_connection(self, port: PortItem):
        """Start dragging a new connection or pick up an existing one."""
        if self._drag_edge is not None:
            self.cancel_connection_drag()

        existing = None
        if port.direction == INPUT:
            existing = self.graph.edge_into(port.node_name, port.port_name)

        if existing is not None:
            # Pick up the far (output) end and re-route it.
            src_item = self.node_items.get(existing.src_node)
            if src_item is None:
                return False
            src_port = src_item.output_ports.get(existing.src_output)
            if src_port is None:
                return False
            self._pending_pickup = existing
            self._drag_port = src_port
        else:
            self._pending_pickup = None
            self._drag_port = port

        self._snap_target = None
        self._drag_edge = DragEdgeItem(self._drag_port.scene_pos())
        self.addItem(self._drag_edge)
        self._highlight_compatible(self._drag_port)
        for node_item in self.node_items.values():
            node_item.setFlag(QtWidgets.QGraphicsItem.ItemIsMovable, False)
        return True

    def update_connection_drag(self, scene_pos: QtCore.QPointF):
        if self._drag_edge is None or self._drag_port is None:
            return
        candidate = self._nearest_compatible_port(
            self._drag_port, scene_pos, style.SNAP_ACQUIRE)
        if candidate is not None:
            self._snap_target = candidate
        self._apply_snap_highlight(self._snap_target)
        end_pos = (self._snap_target.scene_pos()
                   if self._snap_target is not None else scene_pos)
        reverse = self._drag_port.direction == INPUT
        self._drag_edge.update_end(end_pos, reverse=reverse)

    def _restore_node_moving(self):
        for node_item in self.node_items.values():
            node_item.setFlag(QtWidgets.QGraphicsItem.ItemIsMovable, True)

    def finish_connection_drag(self, scene_pos: QtCore.QPointF):
        if self._drag_edge is None:
            return
        grabber = self.mouseGrabberItem()
        if grabber is not None:
            grabber.ungrabMouse()
        self.removeItem(self._drag_edge)
        self._drag_edge = None
        self._clear_highlights()
        target = self._snap_target or self._port_at(scene_pos)
        self._snap_target = None
        self._finish_connection(target)
        self._drag_port = None
        self._pending_pickup = None
        self._restore_node_moving()

    def cancel_connection_drag(self):
        """Abort an in-progress connection drag without changing the graph."""
        grabber = self.mouseGrabberItem()
        if grabber is not None:
            grabber.ungrabMouse()
        if self._drag_edge is not None:
            self.removeItem(self._drag_edge)
        self._drag_edge = None
        self._drag_port = None
        self._pending_pickup = None
        self._clear_highlights()
        self._restore_node_moving()

        self._drag_port = None
        self._pending_pickup = None
        self._snap_target = None
        self._clear_highlights()
        self._restore_node_moving()

    def _nearest_compatible_port(self, from_port: PortItem,
                                 scene_pos: QtCore.QPointF,
                                 max_dist: float):
        """Nearest connectable port of the opposite direction within *max_dist*."""
        want = INPUT if from_port.direction == OUTPUT else OUTPUT
        nearest = None
        nearest_dist = max_dist
        for node_item in self.node_items.values():
            ports = (node_item.input_ports if want == INPUT
                     else node_item.output_ports)
            for port in ports.values():
                if port is from_port:
                    continue
                if from_port.direction == OUTPUT:
                    ok, _ = self.graph.can_connect(
                        from_port.node_name, from_port.port_name,
                        port.node_name, port.port_name)
                else:
                    ok, _ = self.graph.can_connect(
                        port.node_name, port.port_name,
                        from_port.node_name, from_port.port_name)
                if not ok:
                    continue
                dist = QtCore.QLineF(scene_pos, port.scene_pos()).length()
                if dist < nearest_dist:
                    nearest_dist = dist
                    nearest = port
        return nearest

    def _apply_snap_highlight(self, target):
        for node_item in self.node_items.values():
            for port in list(node_item.input_ports.values()) + \
                    list(node_item.output_ports.values()):
                port.set_snap_active(port is target)

    def _highlight_compatible(self, from_port: PortItem):
        want = INPUT if from_port.direction == OUTPUT else OUTPUT
        for node_item in self.node_items.values():
            ports = (node_item.input_ports if want == INPUT
                     else node_item.output_ports)
            for port in ports.values():
                if port is from_port:
                    continue
                if from_port.direction == OUTPUT:
                    ok, _ = self.graph.can_connect(
                        from_port.node_name, from_port.port_name,
                        port.node_name, port.port_name)
                else:
                    ok, _ = self.graph.can_connect(
                        port.node_name, port.port_name,
                        from_port.node_name, from_port.port_name)
                port.set_drag_highlight(bool(ok))

    def _clear_highlights(self):
        for node_item in self.node_items.values():
            for port in list(node_item.input_ports.values()) + \
                    list(node_item.output_ports.values()):
                port.set_drag_highlight(None)
                port.set_snap_active(False)

    def _port_at(self, pos: QtCore.QPointF, tolerance=14.0):
        for item in self.items(pos):
            if isinstance(item, PortItem):
                return item
        nearest = None
        nearest_dist = tolerance
        for node_item in self.node_items.values():
            for port in list(node_item.input_ports.values()) + \
                    list(node_item.output_ports.values()):
                dist = QtCore.QLineF(pos, port.scene_pos()).length()
                if dist < nearest_dist:
                    nearest_dist = dist
                    nearest = port
        return nearest

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self._commit_moves()

    def _finish_connection(self, target):
        src = self._drag_port
        pickup = self._pending_pickup
        if target is None or target is src:
            if pickup is not None:
                # Dropped in empty space: remove the picked-up connection.
                self.stack.push(
                    commands.DisconnectCommand(self.graph, pickup))
            return
        if src.direction == target.direction:
            return

        if src.direction == OUTPUT:
            args = (src.node_name, src.port_name,
                    target.node_name, target.port_name)
        else:
            args = (target.node_name, target.port_name,
                    src.node_name, src.port_name)

        if pickup is not None and \
                (args[2], args[3]) == (pickup.dst_node, pickup.dst_input):
            return  # dropped back where it started

        ok, _reason = self.graph.can_connect(*args)
        if not ok:
            if pickup is not None:
                self.stack.push(
                    commands.DisconnectCommand(self.graph, pickup))
            return
        if pickup is not None:
            self.stack.push(commands.DisconnectCommand(self.graph, pickup))
        self.stack.push(commands.ConnectCommand(self.graph, *args))

    # ----------------------------------------------------- undoable moves

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self._move_start = {
            i.node_name: (i.pos().x(), i.pos().y())
            for i in self.selectedItems() if isinstance(i, NodeItem)}
        self._output_panel_move_start = None
        if self._output_panel is not None and self._output_panel.isSelected():
            pos = self._output_panel.pos()
            self._output_panel_move_start = (pos.x(), pos.y())

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.scenePos(), QtGui.QTransform())
        while item is not None and not isinstance(item, NodeItem):
            item = item.parentItem()
        if isinstance(item, NodeItem):
            self.node_double_clicked.emit(item.node_name)
        super().mouseDoubleClickEvent(event)

    def _commit_moves(self):
        moves = []
        for name, old in self._move_start.items():
            item = self.node_items.get(name)
            if item is None:
                continue
            new = (item.pos().x(), item.pos().y())
            if new != old:
                moves.append((name, old, new))
        self._move_start = {}
        if moves:
            self.stack.push(commands.MoveNodesCommand(self.graph, moves))

        if self._output_panel_move_start and self._output_panel is not None \
                and self.active_scope:
            new = (self._output_panel.pos().x(), self._output_panel.pos().y())
            if new != self._output_panel_move_start:
                self._output_panel_positions[self.active_scope] = new
        self._output_panel_move_start = None

    # -------------------------------------------------------- palette drop

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(NODEDEF_MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(NODEDEF_MIME):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat(NODEDEF_MIME):
            name = bytes(event.mimeData().data(NODEDEF_MIME)).decode("utf-8")
            nodedef = self.library.get(name)
            if nodedef is not None:
                self.add_node_at(nodedef, event.scenePos())
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    # ------------------------------------------------------------- painting

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        step = style.GRID_STEP
        left = int(rect.left()) - int(rect.left()) % step
        top = int(rect.top()) - int(rect.top()) % step

        minor, major = [], []
        x = left
        while x < rect.right():
            line = QtCore.QLineF(x, rect.top(), x, rect.bottom())
            (major if x % (step * style.GRID_MAJOR_EVERY) == 0
             else minor).append(line)
            x += step
        y = top
        while y < rect.bottom():
            line = QtCore.QLineF(rect.left(), y, rect.right(), y)
            (major if y % (step * style.GRID_MAJOR_EVERY) == 0
             else minor).append(line)
            y += step

        painter.setPen(QtGui.QPen(style.GRID_MINOR, 0))
        painter.drawLines(minor)
        painter.setPen(QtGui.QPen(style.GRID_MAJOR, 0))
        painter.drawLines(major)
