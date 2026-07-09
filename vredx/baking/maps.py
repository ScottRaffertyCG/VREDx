# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""Discover bakeable shader inputs from a VredX graph or .mtlx file."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Iterable, List, Optional, Set

from ..core import mtlx_types
from ..core.graph import Graph, connected_inputs

# Legacy / duplicate standard_surface inputs — prefer the modern name.
_EXCLUDED_BAKE_INPUTS = frozenset({
    "base",  # superseded by base_color
})

# Maps shown by default in the UI; more can be added with +.
DEFAULT_MAP_SLOTS: tuple[str, ...] = (
    "base_color",
    "diffuse_roughness",
    "metalness",
    "normal",
)

# Common PBR inputs for standard_surface / open_pbr_surface.
PBR_PRESET_INPUTS: tuple[str, ...] = (
    "base_color",
    "specular_roughness",
    "metalness",
    "normal",
    "opacity",
    "emission_color",
    "transmission_color",
    "subsurface_color",
    "coat_color",
    "coat_roughness",
    "coat_normal",
)

_SHADER_CATEGORIES = frozenset({
    "standard_surface",
    "open_pbr_surface",
    "gltf_pbr",
    "disney_principled",
    "usd_preview_surface",
})

_GEOMETRY_NODE_TYPES = frozenset({
    "texcoord", "geompropvalue", "position", "normal", "tangent",
    "bitangent", "geomcolor", "geomprop", "frame", "time",
})

# Shader input types the ASWF TextureBaker can flatten to images.
_BAKEABLE_INPUT_TYPES = frozenset({
    "color3", "color4", "vector2", "vector3", "vector4",
    "float", "integer", "half", "boolean",
})


@dataclass(frozen=True)
class BakeMap:
    """One shader input that can be baked to a texture."""
    input_name: str
    shader_name: str
    material_name: str
    connected_node: str
    value_type: str


def discover_bake_maps(graph: Graph) -> List[BakeMap]:
    """Return all bakeable shader inputs for the graph."""
    materials = graph.material_nodes()
    if not materials:
        raw = _discover_from_shaders(graph, material_name=graph.name)
    else:
        raw = []
        for material in materials:
            shader = _find_surface_shader(graph, material)
            if shader is None:
                continue
            raw.extend(_discover_from_shader_node(
                graph, shader, material_name=material.name))
    return _filter_catalog(raw)


def catalog_bake_maps(graph: Graph) -> List[BakeMap]:
    """Bakeable inputs available to add in the UI (excludes legacy names)."""
    return discover_bake_maps(graph)


def discover_bake_maps_from_mtlx(path: str) -> List[BakeMap]:
    """Parse a saved .mtlx file without loading into Graph."""
    tree = ET.parse(path)
    root = tree.getroot()
    results: List[BakeMap] = []
    material_name = graph_name_from_root(root)
    for elem in root.iter():
        if elem.tag != "standard_surface" and elem.tag not in _SHADER_CATEGORIES:
            continue
        shader_name = elem.get("name", "")
        for child in elem:
            if child.tag != "input":
                continue
            nodename = child.get("nodename")
            if not nodename:
                continue
            results.append(BakeMap(
                input_name=child.get("name", ""),
                shader_name=shader_name,
                material_name=material_name,
                connected_node=nodename,
                value_type=child.get("type", ""),
            ))
    return results


def graph_name_from_root(root: ET.Element) -> str:
    for elem in root:
        if elem.tag == "surfacematerial":
            return elem.get("name", "material")
    return "material"


def filter_maps(maps: Iterable[BakeMap], selected: Optional[Set[str]]) -> List[BakeMap]:
    if not selected:
        return list(maps)
    return [m for m in maps if m.input_name in selected]


def filter_baked_images(
    images: dict,
    previews: dict,
    maps: Iterable[BakeMap],
    *,
    allowed_names: Optional[Set[str]] = None,
) -> tuple[dict, dict]:
    """Keep only shader-input keys (drop internal MaterialX image node names)."""
    allowed = allowed_names or {m.input_name for m in maps}
    filtered_images = {k: v for k, v in images.items() if k in allowed}
    filtered_previews = {k: v for k, v in previews.items() if k in allowed}
    return filtered_images, filtered_previews


def input_name_from_bake_filename(
    filename: str,
    allowed: Optional[Set[str]] = None,
) -> Optional[str]:
    """Map a baked texture filename back to a shader input name."""
    stem = _normalize_bake_stem(filename)
    if not allowed:
        return stem.split("_")[-1] if "_" in stem else stem
    for name in sorted(allowed, key=len, reverse=True):
        if stem == name or stem.endswith("_" + name):
            return name
    return None


def _normalize_bake_stem(filename: str) -> str:
    """Strip repeated extensions (ASWF may emit ``name.png..png``)."""
    name = os.path.basename(filename)
    known = (".png", ".exr", ".jpg", ".jpeg")
    changed = True
    while changed:
        changed = False
        name = name.rstrip(".")
        lower = name.lower()
        for ext in known:
            if lower.endswith(ext):
                name = name[:-len(ext)]
                changed = True
                break
    return name


def _filter_catalog(maps: Iterable[BakeMap]) -> List[BakeMap]:
    return [m for m in maps if m.input_name not in _EXCLUDED_BAKE_INPUTS]


def pbr_preset_names(maps: Iterable[BakeMap]) -> List[str]:
    available = {m.input_name for m in maps}
    return [name for name in PBR_PRESET_INPUTS if name in available]


def has_geometry_dependent_nodes(graph: Graph) -> bool:
    for node in graph.nodes.values():
        category = (node.category or "").lower()
        if category in _GEOMETRY_NODE_TYPES:
            return True
    return False


def _discover_from_shaders(graph: Graph, material_name: str) -> List[BakeMap]:
    results: List[BakeMap] = []
    for shader in graph.surface_shader_nodes():
        results.extend(_discover_from_shader_node(
            graph, shader, material_name=material_name))
    return results


def _find_surface_shader(graph: Graph, material):
    for edge in graph.edges:
        if edge.dst_node != material.name:
            continue
        if edge.dst_input != "surfaceshader":
            continue
        source = graph.nodes.get(edge.src_node)
        if source is not None:
            return source
    return None


def _discover_from_shader_node(graph: Graph, shader, material_name: str) -> List[BakeMap]:
    """All bakeable shader inputs (connected graphs and literal values)."""
    conn_src: dict[str, str] = {}
    for edge in graph.edges:
        if edge.dst_node != shader.name:
            continue
        conn_src[edge.dst_input] = edge.src_node

    results: List[BakeMap] = []
    for idef in shader.nodedef.inputs:
        if not _is_bakeable_input(idef):
            continue
        results.append(BakeMap(
            input_name=idef.name,
            shader_name=shader.name,
            material_name=material_name,
            connected_node=conn_src.get(idef.name, ""),
            value_type=idef.type,
        ))
    return results


def _is_bakeable_input(idef) -> bool:
    if idef.name in _EXCLUDED_BAKE_INPUTS:
        return False
    if mtlx_types.is_shader_type(idef.type):
        return False
    return idef.type.lower() in _BAKEABLE_INPUT_TYPES
