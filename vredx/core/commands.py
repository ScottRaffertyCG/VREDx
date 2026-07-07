# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""Undoable commands over a :class:`vredx.core.graph.Graph`.

Classic command pattern: the UI never mutates the graph directly, it
pushes commands onto a :class:`CommandStack`.  Everything here is pure
Python so undo/redo invariants can be tested headlessly.
"""

from typing import List, Optional, Tuple

from .graph import Edge, Graph, GraphError, Node
from .nodedef_library import NodeDef


class Command:
    """Base command.  Subclasses implement redo()/undo()."""

    label = "Command"

    def redo(self):
        raise NotImplementedError

    def undo(self):
        raise NotImplementedError


class CommandStack:
    """Undo/redo stack with a change notification hook for the UI."""

    def __init__(self, limit: int = 200):
        self._undo: List[Command] = []
        self._redo: List[Command] = []
        self._limit = limit
        # Called with no args after any command executes/undoes/redoes.
        self.changed_callbacks = []

    def push(self, command: Command, merge: bool = False):
        """Execute a command and record it.

        With merge=True, consecutive commands that support merge_with()
        (e.g. slider drags on the same input) collapse into one undo step.
        """
        command.redo()
        if merge and self._undo and hasattr(self._undo[-1], "merge_with") \
                and type(self._undo[-1]) is type(command) \
                and self._undo[-1].merge_with(command):
            pass
        else:
            self._undo.append(command)
            if len(self._undo) > self._limit:
                self._undo.pop(0)
        self._redo.clear()
        self._notify()

    def undo(self) -> Optional[Command]:
        if not self._undo:
            return None
        command = self._undo.pop()
        command.undo()
        self._redo.append(command)
        self._notify()
        return command

    def redo(self) -> Optional[Command]:
        if not self._redo:
            return None
        command = self._redo.pop()
        command.redo()
        self._undo.append(command)
        self._notify()
        return command

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def clear(self):
        self._undo.clear()
        self._redo.clear()
        self._notify()

    def _notify(self):
        for cb in list(self.changed_callbacks):
            cb()


# ------------------------------------------------------------------ commands

class AddNodeCommand(Command):
    def __init__(self, graph: Graph, nodedef: NodeDef,
                 name: Optional[str] = None,
                 position: Tuple[float, float] = (0.0, 0.0),
                 compound: Optional[str] = None):
        self.graph = graph
        self.nodedef = nodedef
        self.requested_name = name
        self.position = position
        self.compound = compound
        self.node: Optional[Node] = None
        self.label = "Add %s" % nodedef.node

    def redo(self):
        if self.node is None:
            self.node = self.graph.add_node(
                self.nodedef, self.requested_name, self.position,
                compound=self.compound)
        else:
            self.graph.restore_node(self.node, [])

    def undo(self):
        self.graph.remove_node(self.node.name)


class RemoveNodesCommand(Command):
    """Remove several nodes (and their edges) as one undo step."""

    def __init__(self, graph: Graph, names: List[str]):
        self.graph = graph
        self.names = list(names)
        self._removed: List[Tuple[Node, List[Edge]]] = []
        self.label = "Delete %d node(s)" % len(self.names)

    def redo(self):
        self._removed = []
        for name in self.names:
            self._removed.append(self.graph.remove_node(name))

    def undo(self):
        # Restore in reverse order; edges may reference other restored nodes,
        # so restore all nodes first, then all edges.
        for node, _ in reversed(self._removed):
            self.graph.restore_node(node, [])
        for _, edges in self._removed:
            self.graph.edges.extend(edges)


class ConnectCommand(Command):
    def __init__(self, graph: Graph, src_node: str, src_output: str,
                 dst_node: str, dst_input: str):
        self.graph = graph
        self.args = (src_node, src_output, dst_node, dst_input)
        self.edge: Optional[Edge] = None
        self.displaced: Optional[Edge] = None
        self.label = "Connect %s -> %s.%s" % (src_node, dst_node, dst_input)

    def redo(self):
        self.edge, self.displaced = self.graph.connect(*self.args)

    def undo(self):
        self.graph.disconnect(self.edge)
        if self.displaced is not None:
            self.graph.edges.append(self.displaced)


class DisconnectCommand(Command):
    def __init__(self, graph: Graph, edge: Edge):
        self.graph = graph
        self.edge = edge
        self.label = "Disconnect %s.%s" % (edge.dst_node, edge.dst_input)

    def redo(self):
        self.graph.disconnect(self.edge)

    def undo(self):
        self.graph.edges.append(self.edge)


class SetValueCommand(Command):
    def __init__(self, graph: Graph, node_name: str, input_name: str, value):
        self.graph = graph
        self.node_name = node_name
        self.input_name = input_name
        self.new_value = value
        self._had_override = False
        self._old_value = None
        self.label = "Set %s.%s" % (node_name, input_name)

    def redo(self):
        node = self.graph.node(self.node_name)
        self._had_override = self.input_name in node.values
        self._old_value = node.values.get(self.input_name)
        node.set_value(self.input_name, self.new_value)

    def undo(self):
        node = self.graph.node(self.node_name)
        if self._had_override:
            node.set_value(self.input_name, self._old_value)
        else:
            node.clear_value(self.input_name)

    def merge_with(self, other: "SetValueCommand") -> bool:
        """Collapse consecutive edits of the same input (slider drags)."""
        if (other.node_name, other.input_name) != \
                (self.node_name, self.input_name):
            return False
        self.new_value = other.new_value
        return True


class SetExposeCommand(Command):
    """Toggle whether nodes appear in VRED's Realistic material editor."""

    def __init__(self, graph: Graph, node_names, exposed: bool):
        self.graph = graph
        if isinstance(node_names, str):
            node_names = [node_names]
        self.node_names = list(node_names)
        self.new_exposed = exposed
        self._old_exposed = {}
        if len(self.node_names) == 1:
            self.label = "%s %s in material" % (
                "Expose" if exposed else "Hide", self.node_names[0])
        else:
            self.label = "%s %d nodes in material" % (
                "Expose" if exposed else "Hide", len(self.node_names))

    def redo(self):
        for name in self.node_names:
            node = self.graph.node(name)
            if name not in self._old_exposed:
                self._old_exposed[name] = node.expose_in_material
            node.expose_in_material = self.new_exposed

    def undo(self):
        for name, old in self._old_exposed.items():
            self.graph.node(name).expose_in_material = old


class MoveNodesCommand(Command):
    """Records node position changes (for undo of canvas drags)."""

    def __init__(self, graph: Graph,
                 moves: List[Tuple[str, Tuple[float, float], Tuple[float, float]]]):
        # moves: [(node_name, old_pos, new_pos), ...]
        self.graph = graph
        self.moves = moves
        self.label = "Move %d node(s)" % len(moves)

    def redo(self):
        for name, _old, new in self.moves:
            self.graph.node(name).position = new

    def undo(self):
        for name, old, _new in self.moves:
            self.graph.node(name).position = old


class RenameNodeCommand(Command):
    def __init__(self, graph: Graph, old_name: str, new_name: str):
        self.graph = graph
        self.old_name = old_name
        self.requested = new_name
        self.actual: Optional[str] = None
        self.label = "Rename %s" % old_name

    def redo(self):
        self.actual = self.graph.rename_node(self.old_name, self.requested)

    def undo(self):
        self.graph.rename_node(self.actual, self.old_name)
