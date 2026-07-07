# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""Serialize a :class:`vredx.core.graph.Graph` to a MaterialX 1.39 document.

Output layout is a *flat* document: every node is a direct child of the
``<materialx>`` root, wired with ``nodename`` references.  This is valid
MaterialX and loads directly in VRED via
``vrdMaterialXMaterial.loadMaterial(path, 0)``.

Determinism: nodes are emitted in topological order (ties broken by
name) and only explicitly-set input values are written, so identical
graphs always produce byte-identical documents - which the test suite
relies on for golden-file comparison.

Node editor positions are stored as ``xpos``/``ypos`` attributes, the
same convention the MaterialX Graph Editor uses, so layout survives a
save/load round-trip and remains compatible with other tools.
"""

import os
import xml.etree.ElementTree as ET
from xml.dom import minidom

from . import mtlx_paths, mtlx_types
from .graph import Graph, can_expose_in_material

MATERIALX_VERSION = "1.39"

# xpos/ypos are stored in abstract grid units in other tools; scale scene
# pixels down so documents look sane in the MaterialX Graph Editor too.
POSITION_SCALE = 0.01


def write_document(graph: Graph, output_path: str = None) -> str:
    """Serialize the graph to a MaterialX XML string."""
    filename_overrides = {}
    if output_path:
        filename_overrides = mtlx_paths.stage_textures_for_output(
            graph, output_path)
    root = ET.Element("materialx")
    root.set("version", MATERIALX_VERSION)
    if graph.colorspace:
        root.set("colorspace", graph.colorspace)

    for node in _emit_order(graph):
        elem = ET.SubElement(root, node.category)
        elem.set("name", node.name)
        elem.set("type", node.output_type)
        _write_position(elem, node)
        for key, value in sorted(node.extra_attrs.items()):
            if key not in ("name", "type", "xpos", "ypos"):
                elem.set(key, value)
        _write_inputs(graph, node, elem, filename_overrides.get(node.name))

    return _pretty(root)


def save_document(graph: Graph, path: str):
    text = write_document(graph, output_path=path)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    graph.document_dir = os.path.dirname(os.path.abspath(path))


# ----------------------------------------------------------------- helpers

def _emit_order(graph: Graph):
    """Topological order: sources first, material node(s) last."""
    order = [n for n in graph.topological_order() if not n.is_compound]
    # Stable tie-break already applied inside topological_order (sorted
    # ready list); additionally push material nodes to the end so the
    # document reads pattern -> shader -> material.
    return sorted(order, key=lambda n: (
        _semantic_rank(n.output_type), order.index(n)))


def _semantic_rank(output_type: str) -> int:
    if output_type == "material":
        return 2
    if mtlx_types.is_shader_type(output_type):
        return 1
    return 0


def _write_position(elem, node):
    x, y = node.position
    if x or y:
        elem.set("xpos", _fmt_pos(x * POSITION_SCALE))
        elem.set("ypos", _fmt_pos(y * POSITION_SCALE))


def _fmt_pos(v: float) -> str:
    return ("%.6f" % v).rstrip("0").rstrip(".")


def _write_inputs(graph: Graph, node, elem, filename_overrides=None):
    """Emit one <input> per connection or explicit value override."""
    filename_overrides = filename_overrides or {}
    connected = {}
    for edge in graph.edges:
        if edge.dst_node == node.name:
            connected[edge.dst_input] = edge

    # Deterministic ordering: nodedef input order, then any extras.
    ordered_names = [i.name for i in node.nodedef.inputs]
    extra = sorted(set(list(node.values) + list(connected)) -
                   set(ordered_names))
    for input_name in ordered_names + extra:
        edge = connected.get(input_name)
        has_value = input_name in node.values
        if edge is None and not has_value:
            continue

        idef = node.nodedef.find_input(input_name)
        input_type = idef.type if idef else "float"
        inp = ET.SubElement(elem, "input")
        inp.set("name", input_name)
        inp.set("type", input_type)

        if edge is not None:
            src_name, src_output = graph.resolve_edge_source(edge)
            src = graph.node(src_name)
            inp.set("nodename", src_name)
            if len(src.nodedef.outputs) > 1 or src_output != "out":
                inp.set("output", src_output)
        else:
            value = filename_overrides.get(input_name, node.values[input_name])
            inp.set("value",
                    mtlx_types.format_value(input_type, value))

        attrs = dict(node.input_attrs.get(input_name, {}))
        if edge is None and can_expose_in_material(node, graph):
            if node.expose_in_material:
                attrs.pop("uivisible", None)
            else:
                attrs["uivisible"] = "false"
        for key, value in sorted(attrs.items()):
            if key not in ("name", "type", "value", "nodename", "output"):
                inp.set(key, value)


def _pretty(root) -> str:
    raw = ET.tostring(root, encoding="unicode")
    text = minidom.parseString(raw).toprettyxml(indent="  ")
    # minidom emits a decl with single quotes and stray blank lines.
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if lines and lines[0].startswith("<?xml"):
        lines[0] = '<?xml version="1.0"?>'
    return "\n".join(lines) + "\n"
