# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.



"""MaterialX filename path helpers and import layout."""



import os

import shutil

from typing import Dict, List, Optional, Tuple



from .graph import Graph, GraphError, Node





def normalize_mtlx_path(path: str) -> str:

    """MaterialX paths use forward slashes; a leading ``/`` is not absolute."""

    return str(path).replace("\\", "/").lstrip("/")





def resolve_filename(path: str, base_dir: str) -> str:

    """Resolve a MaterialX filename against a document directory."""

    if not path or not str(path).strip():

        return path or ""

    text = str(path).strip()

    if os.path.isabs(text):

        return os.path.normpath(text)

    if not base_dir:

        return text

    joined = os.path.join(

        base_dir, normalize_mtlx_path(text).replace("/", os.sep))

    return os.path.normpath(joined)





def locate_texture_file(path: str, base_dir: str) -> Optional[str]:

    """Return an existing file for a MaterialX filename input, if found."""

    candidate = resolve_filename(path, base_dir)

    if candidate and os.path.isfile(candidate):

        return candidate

    if path and os.path.isfile(path):

        return os.path.normpath(path)

    return None





def absolutize_graph_filenames(graph: Graph) -> None:

    """Turn resolvable relative filename inputs into absolute paths."""

    base = graph.document_dir or ""

    for node in graph.nodes.values():

        for idef in node.nodedef.inputs:

            if idef.type != "filename":

                continue

            if idef.name not in node.values:

                continue

            val = node.values[idef.name]

            if not val:

                continue

            resolved = locate_texture_file(str(val), base)

            if resolved:

                node.values[idef.name] = resolved





def stage_textures_for_output(graph: Graph,

                              output_mtlx_path: str) -> Dict[str, Dict[str, str]]:

    """Copy referenced textures beside *output_mtlx_path*.



    Returns per-node filename overrides (MaterialX-relative paths) for

    the writer.  The in-memory graph is not modified.

    """

    output_dir = os.path.dirname(os.path.abspath(output_mtlx_path))

    os.makedirs(output_dir, exist_ok=True)

    overrides: Dict[str, Dict[str, str]] = {}

    base = graph.document_dir or ""



    for node in graph.nodes.values():

        for idef in node.nodedef.inputs:

            if idef.type != "filename":

                continue

            if idef.name not in node.values:

                continue

            val = node.values[idef.name]

            if not val:

                continue

            src = locate_texture_file(str(val), base)

            if not src:

                continue

            rel = normalize_mtlx_path(str(val))

            if os.path.isabs(str(val)) or ":" in rel or not rel:

                rel = "textures/" + os.path.basename(src)

            elif rel == os.path.basename(src):

                rel = "textures/" + os.path.basename(src)

            dest = os.path.join(output_dir, rel.replace("/", os.sep))

            os.makedirs(os.path.dirname(dest), exist_ok=True)

            if os.path.normcase(src) != os.path.normcase(dest):

                shutil.copy2(src, dest)

            overrides.setdefault(node.name, {})[idef.name] = rel

    return overrides





def auto_layout_nodes(graph: Graph,
                      spacing: Optional[Tuple[float, float]] = None) -> None:
    """Place nodes left-to-right within each graph scope (root + compounds)."""
    for scope in [None] + sorted(graph.compounds.keys()):
        _layout_scope(graph, scope, spacing)


def _spacing_for_count(count: int) -> Tuple[float, float]:
    """Tighter columns for small graphs; wider for dense nodegraphs."""
    if count <= 3:
        return (350.0, 120.0)
    if count <= 10:
        return (200.0, 140.0)
    return (300.0, 160.0)


def _layout_scope(graph: Graph, scope: Optional[str],
                  spacing_override: Optional[Tuple[float, float]] = None) -> None:
    names = graph.nodes_in_scope(scope)
    if not names:
        return
    nodes = [graph.node(name) for name in names]
    spacing = spacing_override or _spacing_for_count(len(nodes))
    spacing_x, spacing_y = spacing

    if len(nodes) <= 1:
        nodes[0].position = (0.0, 0.0)
        return

    visible = set(names)
    scoped_edges = [e for e in graph.edges
                    if e.src_node in visible and e.dst_node in visible]

    try:
        order = _topological_order(names, scoped_edges, graph)
    except GraphError:
        order = sorted(nodes, key=lambda n: n.name)

    depths = _node_depths_scoped(names, scoped_edges, order)
    surfaces = [n for n in order if n.output_type == "surfaceshader"]
    materials = [n for n in order if n.output_type == "material"]
    pinned = {n.name for n in surfaces + materials}
    middle = [n for n in order if n.name not in pinned]

    max_middle_depth = max((depths[n.name] for n in middle), default=-1)
    surface_col = max_middle_depth + 1
    material_col = max_middle_depth + 2

    rows_by_depth: Dict[int, List[Node]] = {}
    for node in middle:
        rows_by_depth.setdefault(depths[node.name], []).append(node)
    for depth in rows_by_depth:
        rows_by_depth[depth].sort(key=lambda n: n.name)
        for row, node in enumerate(rows_by_depth[depth]):
            node.position = (depth * spacing_x, row * spacing_y)

    surface_for_material = {}
    for material in materials:
        for edge in scoped_edges:
            if edge.dst_node == material.name and edge.dst_input == "surfaceshader":
                surface_for_material[material.name] = edge.src_node
                break

    assigned = set()
    row = 0
    for material in sorted(materials, key=lambda n: n.name):
        surf_name = surface_for_material.get(material.name)
        if surf_name is None or surf_name in assigned:
            continue
        surface = graph.node(surf_name)
        y = row * spacing_y
        surface.position = (surface_col * spacing_x, y)
        material.position = (material_col * spacing_x, y)
        assigned.add(surf_name)
        assigned.add(material.name)
        row += 1

    for surface in sorted(surfaces, key=lambda n: n.name):
        if surface.name in assigned:
            continue
        surface.position = (surface_col * spacing_x, row * spacing_y)
        assigned.add(surface.name)
        row += 1

    for material in sorted(materials, key=lambda n: n.name):
        if material.name in assigned:
            continue
        material.position = (material_col * spacing_x, row * spacing_y)
        assigned.add(material.name)
        row += 1


def _topological_order(names, scoped_edges, graph: Graph) -> List[Node]:
    name_set = set(names)
    indegree = {name: 0 for name in names}
    for edge in scoped_edges:
        if edge.dst_node in indegree:
            indegree[edge.dst_node] += 1
    ready = sorted(n for n, d in indegree.items() if d == 0)
    order: List[Node] = []
    edges_from = {}
    for edge in scoped_edges:
        edges_from.setdefault(edge.src_node, []).append(edge)
    while ready:
        name = ready.pop(0)
        order.append(graph.node(name))
        for edge in sorted(edges_from.get(name, ()),
                           key=lambda e: (e.dst_node, e.dst_input)):
            if edge.dst_node not in indegree:
                continue
            indegree[edge.dst_node] -= 1
            if indegree[edge.dst_node] == 0:
                ready.append(edge.dst_node)
        ready.sort()
    if len(order) != len(names):
        raise GraphError("Graph contains a cycle")
    return order


def _node_depths_scoped(names, scoped_edges, order: List[Node]) -> Dict[str, int]:
    preds = {name: [] for name in names}
    for edge in scoped_edges:
        if edge.dst_node in preds:
            preds[edge.dst_node].append(edge.src_node)
    depths = {}
    for node in order:
        upstream = preds.get(node.name) or []
        depths[node.name] = max((depths[src] for src in upstream), default=-1) + 1
    return depths


def _node_depths(graph: Graph, order: List[Node]) -> Dict[str, int]:

    """Longest-path depth from graph sources (left-to-right layering)."""

    preds = {name: [] for name in graph.nodes}

    for edge in graph.edges:

        preds[edge.dst_node].append(edge.src_node)

    depths = {}

    for node in order:

        upstream = preds.get(node.name) or []

        depths[node.name] = max((depths[src] for src in upstream), default=-1) + 1

    return depths


