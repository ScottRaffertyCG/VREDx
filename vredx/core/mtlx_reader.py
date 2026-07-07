# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""Parse a MaterialX document into an editable :class:`Graph`.

Handles both layouts found in the wild:

* flat documents (what :mod:`vredx.core.mtlx_writer` produces), and
* nodegraph-based documents (typical DCC exports, VRED-shipped BxDF
  graphs): compound ``<nodegraph>`` contents are kept in nested scopes
  and represented by group nodes at the parent level; ``<output>``
  indirections become compound output ports.

Nodes whose definition is unknown to the library are preserved as
*opaque* nodes (with synthesized definitions) instead of failing, so
foreign or newer documents still open with warnings.
"""

import os
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

from . import mtlx_archive, mtlx_paths, mtlx_types
from .graph import (Graph, Node, make_compound_nodedef, make_opaque_nodedef,
                    sync_expose_in_material, CompoundOutput)
from .mtlx_writer import POSITION_SCALE
from .nodedef_library import InputDef, NodeDefLibrary

# Document-level elements that are not scene nodes.
_NON_NODE_TAGS = {
    "nodedef", "nodegraph", "typedef", "unittypedef", "unitdef",
    "geompropdef", "implementation", "attributedef", "targetdef",
    "output", "backdrop", "comment", "collection", "geominfo",
    "look", "lookgroup", "materialassign", "propertyset", "variantset",
    "token",
}

_STRUCTURAL_INPUT_ATTRS = {
    "name", "type", "value", "nodename", "nodegraph", "output",
    "interfacename",
}


class ReadResult:
    def __init__(self, graph: Graph, warnings: List[str]):
        self.graph = graph
        self.warnings = warnings


def load_document(path: str, library: NodeDefLibrary,
                  archive_member: str = None) -> ReadResult:
    temp_root = ""
    mtlx_path = path
    if mtlx_archive.is_zip_path(path):
        temp_root, mtlx_path = mtlx_archive.extract_zip(
            path, member=archive_member)
    with open(mtlx_path, "r", encoding="utf-8") as handle:
        result = read_document(handle.read(), library, name_hint=mtlx_path)
    result.graph.document_dir = os.path.dirname(os.path.abspath(mtlx_path))
    result.graph.source_mtlx_path = os.path.abspath(mtlx_path)
    result.graph.temp_extract_dir = temp_root
    mtlx_paths.absolutize_graph_filenames(result.graph)
    return result


def read_document(text: str, library: NodeDefLibrary,
                  name_hint: str = "imported") -> ReadResult:
    root = ET.fromstring(text)
    if root.tag != "materialx":
        raise ValueError("Not a MaterialX document (root element is <%s>)"
                         % root.tag)
    warnings: List[str] = []
    graph = Graph(_basename(name_hint))
    graph.colorspace = root.get("colorspace", graph.colorspace)

    # name in source doc (possibly nodegraph-qualified) -> graph node name
    name_map: Dict[str, str] = {}
    # (qualified name) -> element, for the connection pass
    node_elems: List[Tuple[str, ET.Element, str]] = []  # (qual, elem, prefix)
    # nodegraph outputs: "ng/outname" -> (internal qual nodename, output, type)
    ng_outputs: Dict[str, Tuple[str, str, str]] = {}
    compound_names: List[str] = []
    had_editor_positions = False

    # Functional (nodedef-implementing) nodegraphs are library plumbing,
    # not scene content.  They are marked either by a nodedef attribute
    # on the nodegraph or by an <implementation nodegraph="..."> element.
    functional_graphs = {
        elem.get("nodegraph")
        for elem in root
        if _strip_ns(elem.tag) == "implementation" and elem.get("nodegraph")
    }

    # ---------------------------------------------------------- pass 1: nodes
    for elem in root:
        tag = _strip_ns(elem.tag)
        if tag == "nodegraph":
            if elem.get("nodedef") or elem.get("name") in functional_graphs:
                continue  # functional graph implementing a nodedef: skip
            ng_name = elem.get("name", "nodegraph")
            compound_names.append(ng_name)
            for child in elem:
                ctag = _strip_ns(child.tag)
                if ctag == "output":
                    out_name = child.get("name", "out")
                    ng_outputs["%s/%s" % (ng_name, out_name)] = (
                        "%s/%s" % (ng_name, child.get("nodename", "")),
                        child.get("output", "out"),
                        child.get("type", "float"))
                    continue
                if ctag in _NON_NODE_TAGS:
                    continue
                qual = "%s/%s" % (ng_name, child.get("name", ""))
                node_elems.append((qual, child, ng_name))
                if child.get("xpos") is not None or child.get("ypos") is not None:
                    had_editor_positions = True
        elif tag in _NON_NODE_TAGS or tag is ET.Comment:
            continue
        else:
            node_elems.append((elem.get("name", ""), elem, ""))
            if elem.get("xpos") is not None or elem.get("ypos") is not None:
                had_editor_positions = True

    for qual, elem, prefix in node_elems:
        node = _create_node(graph, elem, library, warnings,
                            compound=prefix or None)
        name_map[qual] = node.name

    for ng_name in compound_names:
        outputs = _compound_outputs(graph, ng_name, ng_outputs, name_map)
        if not outputs:
            continue
        graph.compounds[ng_name] = outputs
        proxy = graph.add_node(
            make_compound_nodedef(ng_name, outputs),
            name=ng_name, is_compound=True)
        name_map[ng_name] = proxy.name

    # ------------------------------------------------------ pass 2: edges
    for qual, elem, prefix in node_elems:
        dst_name = name_map[qual]
        for inp in elem:
            if _strip_ns(inp.tag) != "input":
                continue
            input_name = inp.get("name", "")
            src_qual, src_output = _resolve_source(
                inp, prefix, ng_outputs)
            if src_qual is None:
                continue
            src_name = name_map.get(src_qual)
            if src_name is None:
                warnings.append(
                    "Connection source '%s' for %s.%s not found; dropped."
                    % (src_qual, dst_name, input_name))
                continue
            _make_edge(graph, src_name, src_output, dst_name, input_name,
                       warnings)

    if not had_editor_positions and len(graph.nodes) > 1:
        mtlx_paths.auto_layout_nodes(graph)

    sync_expose_in_material(graph)

    return ReadResult(graph, warnings)


# ----------------------------------------------------------------- helpers

def _pick_variant(library: NodeDefLibrary, category: str, out_type: str,
                  elem: ET.Element):
    """Choose the nodedef variant whose input signature matches the
    document's typed inputs, not just the output type.

    e.g. <multiply type="color3"> with a float "in2" input must resolve
    to ND_multiply_color3FA (color3 * float), not ND_multiply_color3.
    """
    declared = {
        inp.get("name"): inp.get("type")
        for inp in elem
        if _strip_ns(inp.tag) == "input" and inp.get("type")
    }
    best, best_score = None, -1
    for nd in library.variants(category):
        if nd.output_type != out_type:
            continue
        score = 0
        for name, itype in declared.items():
            found = nd.find_input(name)
            if found is None or found.type != itype:
                score = -1
                break
            score += 1
        if score > best_score:
            best, best_score = nd, score
    return best


def _create_node(graph: Graph, elem: ET.Element, library: NodeDefLibrary,
                 warnings: List[str],
                 compound: Optional[str] = None) -> Node:
    category = _strip_ns(elem.tag)
    out_type = elem.get("type", "none")
    src_name = elem.get("name", category)

    nodedef = None
    explicit = elem.get("nodedef")
    if explicit:
        nodedef = library.get(explicit)
    if nodedef is None:
        nodedef = _pick_variant(library, category, out_type, elem)
    if nodedef is None and library.has_node(category):
        # type overload not found (e.g. multi-output); take first variant
        variants = library.variants(category)
        nodedef = variants[0] if variants else None

    opaque = nodedef is None
    if opaque:
        inputs = [
            InputDef(name=i.get("name", ""), type=i.get("type", "float"),
                     value=mtlx_types.parse_value(i.get("type", "float"),
                                                  i.get("value")))
            for i in elem if _strip_ns(i.tag) == "input"
        ]
        nodedef = make_opaque_nodedef(category, out_type, inputs)
        warnings.append(
            "Unknown node type '%s' (type %s); kept as opaque node."
            % (category, out_type))

    node = graph.add_node(nodedef, name=src_name,
                          position=_read_position(elem), opaque=opaque,
                          compound=compound)
    if node.name != src_name:
        warnings.append("Node '%s' renamed to '%s' (duplicate name)."
                        % (src_name, node.name))

    for key, value in elem.attrib.items():
        if key not in ("name", "type", "xpos", "ypos", "nodedef"):
            node.extra_attrs[key] = value

    for inp in elem:
        if _strip_ns(inp.tag) != "input":
            continue
        input_name = inp.get("name", "")
        value_text = _input_value_text(inp)
        input_type = inp.get("type") or (
            node.nodedef.find_input(input_name).type
            if node.nodedef.find_input(input_name) else "float")
        if value_text is not None and node.nodedef.find_input(input_name):
            node.values[input_name] = mtlx_types.parse_value(
                input_type, value_text)
        extra = {k: v for k, v in inp.attrib.items()
                 if k not in _STRUCTURAL_INPUT_ATTRS}
        if extra:
            node.input_attrs[input_name] = extra

    return node


def _input_value_text(inp: ET.Element) -> Optional[str]:
    text = inp.get("value")
    if text is not None:
        return text
    for child in inp:
        if _strip_ns(child.tag) == "value" and child.text:
            return child.text.strip()
    return None


def _resolve_source(inp: ET.Element, prefix: str,
                    ng_outputs: Dict[str, Tuple[str, str, str]]
                    ) -> Tuple[Optional[str], str]:
    """Return (qualified source node name, source output) for an input."""
    nodename = inp.get("nodename")
    nodegraph = inp.get("nodegraph")
    output = inp.get("output", "out")

    if nodegraph:
        # External reference: connect to the compound proxy output port.
        return nodegraph, output

    if nodename:
        if prefix:
            # Inside a nodegraph, nodename refers to siblings first.
            return "%s/%s" % (prefix, nodename), output
        return nodename, output

    return None, "out"


def _compound_outputs(graph: Graph, ng_name: str,
                      ng_outputs: Dict[str, Tuple[str, str, str]],
                      name_map: Dict[str, str]) -> List[CompoundOutput]:
    """Build compound interface outputs for a nodegraph."""
    outputs: List[CompoundOutput] = []
    prefix = ng_name + "/"
    for key, (qual, internal_output, out_type) in sorted(ng_outputs.items()):
        if not key.startswith(prefix):
            continue
        out_name = key[len(prefix):]
        internal_node = name_map.get(qual)
        if internal_node is None:
            continue
        outputs.append(CompoundOutput(
            name=out_name, type=out_type,
            internal_node=internal_node,
            internal_output=internal_output))
    return outputs


def _make_edge(graph: Graph, src: str, src_output: str,
               dst: str, dst_input: str, warnings: List[str]):
    src_node = graph.node(src)
    if src_node.nodedef.find_output(src_output) is None:
        # Source doc may reference an output name we did not capture
        # (e.g. flattened nodegraph output); fall back to first output.
        if src_node.nodedef.outputs:
            src_output = src_node.nodedef.outputs[0].name
    ok, reason = graph.can_connect(src, src_output, dst, dst_input)
    if ok:
        graph.connect(src, src_output, dst, dst_input)
    else:
        # Keep the document loadable: record and skip.
        warnings.append("Dropped connection %s -> %s.%s: %s"
                        % (src, dst, dst_input, reason))


def _read_position(elem: ET.Element) -> Tuple[float, float]:
    try:
        x = float(elem.get("xpos", "0")) / POSITION_SCALE
        y = float(elem.get("ypos", "0")) / POSITION_SCALE
        return (x, y)
    except ValueError:
        return (0.0, 0.0)


def _strip_ns(tag) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.split("}")[-1]


def _basename(path: str) -> str:
    import os
    stem = os.path.splitext(os.path.basename(path))[0]
    return stem or "imported"
