# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""Pure-Python MaterialX graph document model.

A :class:`Graph` is the single source of truth edited by the UI and
serialized by :mod:`vredx.core.mtlx_writer`.  It knows nothing about Qt
or VRED, which keeps it trivially unit-testable.

Structure mirrors a MaterialX document:

* nodes live in an implicit nodegraph, except shader/material-semantic
  nodes (surfaceshader, material, ...) which sit at document level;
  the writer decides placement, the model does not care.
* every node is an instance of a :class:`NodeDef` from the library, or
  an *opaque* node (unknown definition preserved from an imported file).
"""

import itertools
import re
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

from . import mtlx_types
from .nodedef_library import InputDef, NodeDef, OutputDef


class GraphError(Exception):
    """Raised for illegal graph operations (bad connect, unknown port...)."""


@dataclass
class Edge:
    """A connection: (src node, src output) -> (dst node, dst input)."""
    src_node: str
    src_output: str
    dst_node: str
    dst_input: str

    def key(self) -> Tuple[str, str]:
        """Input ports accept at most one edge; this is that identity."""
        return (self.dst_node, self.dst_input)


class Node:
    """An instance of a MaterialX node in the document."""

    def __init__(self, name: str, nodedef: NodeDef,
                 position: Tuple[float, float] = (0.0, 0.0),
                 opaque: bool = False):
        self.name = name
        self.nodedef = nodedef
        self.position = position
        self.opaque = opaque            # unknown def preserved from import
        # Literal values overriding nodedef defaults, by input name.
        self.values: Dict[str, object] = {}
        # Raw XML attributes preserved for opaque nodes (round-trip).
        self.extra_attrs: Dict[str, str] = {}
        # Extra per-input XML attributes (colorspace, channels, unit...)
        # preserved for round-trip: {input_name: {attr: value}}.
        self.input_attrs: Dict[str, Dict[str, str]] = {}
        # When True, literal inputs are written without uivisible="false" so
        # VRED shows this node in its Realistic material editor.
        self.expose_in_material = False

    # ------------------------------------------------------------ inputs

    @property
    def category(self) -> str:
        return self.nodedef.node

    @property
    def output_type(self) -> str:
        return self.nodedef.output_type

    def input_def(self, name: str) -> InputDef:
        idef = self.nodedef.find_input(name)
        if idef is None:
            raise GraphError("Node '%s' has no input '%s'" % (self.name, name))
        return idef

    def output_def(self, name: str) -> OutputDef:
        odef = self.nodedef.find_output(name)
        if odef is None:
            raise GraphError("Node '%s' has no output '%s'" % (self.name, name))
        return odef

    def get_value(self, input_name: str):
        """Effective literal value: explicit override or nodedef default."""
        if input_name in self.values:
            return self.values[input_name]
        return self.input_def(input_name).value

    def set_value(self, input_name: str, value):
        self.input_def(input_name)  # validate the input exists
        self.values[input_name] = value

    def clear_value(self, input_name: str):
        self.values.pop(input_name, None)

    def is_shader_semantic(self) -> bool:
        return mtlx_types.is_shader_type(self.output_type)


class Graph:
    """The editable document: nodes + edges + document metadata."""

    def __init__(self, name: str = "vredx_material"):
        self.name = name
        self.nodes: Dict[str, Node] = {}
        self.edges: List[Edge] = []
        self.colorspace = "lin_rec709"
        # Directory of the .mtlx file this graph was loaded from or last
        # saved to; used to resolve relative texture paths.
        self.document_dir = ""
        # Temp folder when the graph was loaded from a .zip archive.
        self.temp_extract_dir = ""
        # Absolute path of the .mtlx file backing this graph, if any.
        self.source_mtlx_path = ""

    # ------------------------------------------------------------- nodes

    def add_node(self, nodedef: NodeDef, name: Optional[str] = None,
                 position: Tuple[float, float] = (0.0, 0.0),
                 opaque: bool = False) -> Node:
        node = Node(self.unique_name(name or nodedef.node),
                    nodedef, position, opaque)
        self.nodes[node.name] = node
        return node

    def remove_node(self, name: str) -> Tuple[Node, List[Edge]]:
        """Remove a node and all its edges.  Returns them for undo."""
        node = self.node(name)
        removed = [e for e in self.edges
                   if e.src_node == name or e.dst_node == name]
        self.edges = [e for e in self.edges if e not in removed]
        del self.nodes[name]
        return node, removed

    def restore_node(self, node: Node, edges: List[Edge]):
        if node.name in self.nodes:
            raise GraphError("Node name '%s' already in use" % node.name)
        self.nodes[node.name] = node
        self.edges.extend(edges)

    def rename_node(self, old: str, new: str) -> str:
        node = self.node(old)
        new = self.unique_name(new)
        del self.nodes[old]
        node.name = new
        self.nodes[new] = node
        for e in self.edges:
            if e.src_node == old:
                e.src_node = new
            if e.dst_node == old:
                e.dst_node = new
        return new

    def node(self, name: str) -> Node:
        try:
            return self.nodes[name]
        except KeyError:
            raise GraphError("No node named '%s'" % name)

    def unique_name(self, base: str) -> str:
        base = _sanitize_name(base)
        if base not in self.nodes:
            return base
        stem = re.sub(r"\d+$", "", base) or base
        for i in itertools.count(1):
            candidate = "%s%d" % (stem, i)
            if candidate not in self.nodes:
                return candidate
        raise AssertionError("unreachable")

    # ------------------------------------------------------------- edges

    def can_connect(self, src_node: str, src_output: str,
                    dst_node: str, dst_input: str) -> Tuple[bool, str]:
        """Check legality; returns (ok, reason-if-not)."""
        if src_node == dst_node:
            return False, "Cannot connect a node to itself"
        try:
            src = self.node(src_node)
            dst = self.node(dst_node)
            odef = src.output_def(src_output)
            idef = dst.input_def(dst_input)
        except GraphError as exc:
            return False, str(exc)
        if not mtlx_types.types_compatible(odef.type, idef.type):
            return False, ("Type mismatch: %s output cannot drive %s input"
                           % (odef.type, idef.type))
        if self._creates_cycle(src_node, dst_node):
            return False, "Connection would create a cycle"
        return True, ""

    def connect(self, src_node: str, src_output: str,
                dst_node: str, dst_input: str) -> Tuple[Edge, Optional[Edge]]:
        """Create an edge.  Returns (new edge, displaced edge or None)."""
        ok, reason = self.can_connect(src_node, src_output, dst_node, dst_input)
        if not ok:
            raise GraphError(reason)
        edge = Edge(src_node, src_output, dst_node, dst_input)
        displaced = self.edge_into(dst_node, dst_input)
        if displaced is not None:
            self.edges.remove(displaced)
        self.edges.append(edge)
        return edge, displaced

    def disconnect(self, edge: Edge):
        try:
            self.edges.remove(edge)
        except ValueError:
            # match by value, the UI may hold a different instance
            for e in list(self.edges):
                if (e.src_node, e.src_output, e.dst_node, e.dst_input) == \
                        (edge.src_node, edge.src_output, edge.dst_node, edge.dst_input):
                    self.edges.remove(e)
                    return
            raise GraphError("Edge not found")

    def edge_into(self, dst_node: str, dst_input: str) -> Optional[Edge]:
        for e in self.edges:
            if e.dst_node == dst_node and e.dst_input == dst_input:
                return e
        return None

    def edges_from(self, src_node: str) -> List[Edge]:
        return [e for e in self.edges if e.src_node == src_node]

    def edges_of(self, node_name: str) -> List[Edge]:
        return [e for e in self.edges
                if e.src_node == node_name or e.dst_node == node_name]

    def _creates_cycle(self, src_node: str, dst_node: str) -> bool:
        """Would src->dst close a loop?  True if src is reachable from dst."""
        seen = set()
        stack = [dst_node]
        while stack:
            current = stack.pop()
            if current == src_node:
                return True
            if current in seen:
                continue
            seen.add(current)
            stack.extend(e.dst_node for e in self.edges
                         if e.src_node == current)
        return False

    # --------------------------------------------------------- traversal

    def upstream(self, node_name: str) -> Iterator[Node]:
        """All nodes feeding into node_name (depth-first, deduplicated)."""
        seen = set()
        stack = [node_name]
        while stack:
            current = stack.pop()
            for e in self.edges:
                if e.dst_node == current and e.src_node not in seen:
                    seen.add(e.src_node)
                    stack.append(e.src_node)
                    yield self.nodes[e.src_node]

    def material_nodes(self) -> List[Node]:
        return [n for n in self.nodes.values()
                if n.output_type == "material"]

    def surface_shader_nodes(self) -> List[Node]:
        return [n for n in self.nodes.values()
                if n.output_type == "surfaceshader"]

    def topological_order(self) -> List[Node]:
        """Nodes sorted so that every edge goes from earlier to later."""
        indegree = {name: 0 for name in self.nodes}
        for e in self.edges:
            if e.dst_node in indegree:
                indegree[e.dst_node] += 1
        ready = sorted(n for n, d in indegree.items() if d == 0)
        order: List[Node] = []
        while ready:
            name = ready.pop(0)
            order.append(self.nodes[name])
            for e in sorted(self.edges_from(name),
                            key=lambda e: (e.dst_node, e.dst_input)):
                indegree[e.dst_node] -= 1
                if indegree[e.dst_node] == 0:
                    ready.append(e.dst_node)
            ready.sort()
        if len(order) != len(self.nodes):
            raise GraphError("Graph contains a cycle")
        return order


def connected_inputs(graph: Graph, node_name: str) -> set:
    """Input port names on *node_name* that have an incoming edge."""
    return {e.dst_input for e in graph.edges if e.dst_node == node_name}


def material_ui_inputs(node: Node, connected: set) -> Iterator[str]:
    """Unconnected, non-shader inputs VRED can show in the material editor."""
    for idef in node.nodedef.inputs:
        if idef.name in connected:
            continue
        if mtlx_types.is_shader_type(idef.type):
            continue
        yield idef.name


def can_expose_in_material(node: Node, graph: Graph) -> bool:
    """Whether the inspector may offer an 'Expose in material' toggle."""
    if node.is_shader_semantic():
        return False
    connected = connected_inputs(graph, node.name)
    return any(True for _ in material_ui_inputs(node, connected))


def infer_expose_in_material(node: Node, graph: Graph) -> bool:
    """Derive expose flag from uivisible attributes on imported inputs."""
    if not can_expose_in_material(node, graph):
        return False
    connected = connected_inputs(graph, node.name)
    written = [name for name in material_ui_inputs(node, connected)
               if name in node.values]
    if not written:
        return False
    return any(node.input_attrs.get(name, {}).get("uivisible") != "false"
               for name in written)


def sync_expose_in_material(graph: Graph) -> None:
    """Set :attr:`Node.expose_in_material` on every node after import."""
    for node in graph.nodes.values():
        node.expose_in_material = infer_expose_in_material(node, graph)


def _sanitize_name(name: str) -> str:
    """MaterialX element names: alphanumerics and underscores only."""
    name = re.sub(r"[^A-Za-z0-9_]", "_", name.strip())
    if not name or name[0].isdigit():
        name = "n_" + name
    return name


def make_opaque_nodedef(category: str, output_type: str,
                        inputs: List[InputDef]) -> NodeDef:
    """Synthesize a NodeDef for a node whose definition is unknown.

    Used by the reader so that documents containing custom or newer nodes
    still open (with warnings) instead of failing.
    """
    return NodeDef(
        name="OPAQUE_%s_%s" % (category, output_type),
        node=category,
        nodegroup="unknown",
        doc="Unknown node definition preserved from imported document.",
        inputs=inputs,
        outputs=[OutputDef(name="out", type=output_type)],
    )
