# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""Pre-flight validation of a graph before it is sent to VRED.

Rules combine generic MaterialX correctness (types, cycles, outputs)
with VRED-2027-specific knowledge gathered from the API docs and the
Autodesk forum:

* MaterialX displacement is known-broken in VRED as of Jan 2026
  (Autodesk staff, forum thread 13975031).
* Thin-film effects require full GI raytracing (forum thread 12846804).
* geompropvalue scene-data lookups work in Raytracing/Vulkan only
  (VRED docs, SceneData_GeomProps).
"""

from dataclasses import dataclass
from typing import List, Optional

from . import mtlx_types
from .graph import Graph, GraphError
from .nodedef_library import NodeDefLibrary

ERROR = "error"
WARNING = "warning"
INFO = "info"


@dataclass
class Issue:
    severity: str                  # ERROR / WARNING / INFO
    message: str
    node: Optional[str] = None     # node name, if issue is node-specific

    def __str__(self):
        prefix = self.severity.upper()
        if self.node:
            return "[%s] %s: %s" % (prefix, self.node, self.message)
        return "[%s] %s" % (prefix, self.message)


@dataclass
class ValidationResult:
    issues: List[Issue]

    @property
    def errors(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == ERROR]

    @property
    def warnings(self) -> List[Issue]:
        return [i for i in self.issues if i.severity == WARNING]

    @property
    def ok(self) -> bool:
        """True when the document can be loaded by VRED (no errors)."""
        return not self.errors


def validate(graph: Graph, library: Optional[NodeDefLibrary] = None
             ) -> ValidationResult:
    issues: List[Issue] = []
    _check_outputs(graph, issues)
    _check_cycles(graph, issues)
    _check_connections(graph, issues)
    _check_unknown_nodes(graph, library, issues)
    _check_vred_caveats(graph, issues)
    return ValidationResult(issues)


def _is_vredx_only_node(node) -> bool:
    """Nodes that exist for VredX editing but are not sent to VRED."""
    return node.is_compound


# ----------------------------------------------------------------- checks

def _check_outputs(graph: Graph, issues: List[Issue]):
    materials = graph.material_nodes()
    if not materials:
        surfaces = graph.surface_shader_nodes()
        if surfaces:
            issues.append(Issue(
                ERROR,
                "No material node. Add a 'surfacematerial' node and connect "
                "your surface shader to it."))
        else:
            issues.append(Issue(
                ERROR,
                "Document has no material output. Add a surface shader "
                "(e.g. standard_surface or open_pbr_surface) and a "
                "'surfacematerial' node."))
        return
    if len(materials) > 1:
        issues.append(Issue(
            WARNING,
            "Document contains %d material nodes. VRED loads one material "
            "per vrdMaterialXMaterial; the first will be used by default."
            % len(materials)))
    for mat in materials:
        edge = graph.edge_into(mat.name, "surfaceshader")
        if mat.category == "surfacematerial" and edge is None:
            issues.append(Issue(
                ERROR,
                "surfacematerial node has no surface shader connected.",
                node=mat.name))


def _check_cycles(graph: Graph, issues: List[Issue]):
    try:
        graph.topological_order()
    except GraphError:
        issues.append(Issue(ERROR, "Graph contains a connection cycle."))


def _check_connections(graph: Graph, issues: List[Issue]):
    for edge in graph.edges:
        try:
            src = graph.node(edge.src_node)
            dst = graph.node(edge.dst_node)
            if _is_vredx_only_node(src) or _is_vredx_only_node(dst):
                continue
            src_type = src.output_def(edge.src_output).type
            dst_type = dst.input_def(edge.dst_input).type
        except Exception as exc:
            issues.append(Issue(ERROR, "Broken connection: %s" % exc))
            continue
        if not mtlx_types.types_compatible(src_type, dst_type):
            issues.append(Issue(
                ERROR,
                "Type mismatch: %s.%s (%s) -> %s.%s (%s)"
                % (edge.src_node, edge.src_output, src_type,
                   edge.dst_node, edge.dst_input, dst_type)))
        elif mtlx_types.is_soft_conversion(src_type, dst_type):
            # VRED's MaterialX runtime rejects mismatched port connections
            # outright ("Mismatched types in port connection"), so what the
            # spec calls an implicit conversion is a hard error here.
            issues.append(Issue(
                ERROR,
                "Implicit conversion %s -> %s on %s.%s: VRED rejects "
                "mismatched port connections. Insert a 'convert' node or "
                "use a matching node variant (e.g. multiply color3FA for "
                "color3 * float)."
                % (src_type, dst_type, edge.dst_node, edge.dst_input),
                node=edge.dst_node))


def _check_unknown_nodes(graph: Graph, library: Optional[NodeDefLibrary],
                         issues: List[Issue]):
    for node in graph.nodes.values():
        if _is_vredx_only_node(node):
            continue
        if node.opaque:
            issues.append(Issue(
                WARNING,
                "Node type '%s' has no definition in VRED's MaterialX "
                "libraries; it was preserved from an imported file and may "
                "fail to compile." % node.category,
                node=node.name))
        elif library is not None and not library.has_node(node.category):
            issues.append(Issue(
                ERROR,
                "Node type '%s' is not present in this VRED install's "
                "MaterialX libraries." % node.category,
                node=node.name))


def _check_vred_caveats(graph: Graph, issues: List[Issue]):
    for node in graph.nodes.values():
        if _is_vredx_only_node(node):
            continue
        category = node.category

        if category in ("displacement", "displacementshader") or \
                node.output_type == "displacementshader":
            issues.append(Issue(
                WARNING,
                "MaterialX displacement is known to be broken in VRED "
                "(Autodesk, Jan 2026). The material will load but "
                "displacement may not render.",
                node=node.name))

        if category == "surfacematerial":
            edge = graph.edge_into(node.name, "displacementshader")
            if edge is not None:
                issues.append(Issue(
                    WARNING,
                    "Displacement connected to surfacematerial: VRED's "
                    "MaterialX displacement support is currently broken.",
                    node=node.name))

        if category == "geompropvalue":
            issues.append(Issue(
                INFO,
                "geompropvalue scene-data lookups are evaluated in VRED's "
                "Raytracing and Vulkan renderers only.",
                node=node.name))

        if category in ("thin_film_bsdf",):
            issues.append(Issue(
                INFO,
                "Thin-film effects require full GI raytracing in VRED; "
                "OpenGL/Vulkan raster preview will not show them.",
                node=node.name))

        if category == "standard_surface":
            thin_film = node.get_value("thin_film_thickness")
            if isinstance(thin_film, (int, float)) and thin_film > 0:
                issues.append(Issue(
                    INFO,
                    "standard_surface thin film is active: requires full GI "
                    "raytracing in VRED to be visible.",
                    node=node.name))

    # Unconnected image filenames.
    for node in graph.nodes.values():
        if _is_vredx_only_node(node):
            continue
        if node.category not in ("image", "tiledimage"):
            continue
        value = node.get_value("file")
        if not value:
            issues.append(Issue(
                WARNING,
                "Image node has no file set; it will sample its default "
                "color.",
                node=node.name))
