# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""Phase 3 spike: export VRED mesh data for MaterialX mesh-aware baking.

Per-mesh UV-layout MaterialX baking is not yet supported in VredX.
This module documents the export path and builds a minimal mesh snapshot
for future experiments with ASWF TextureBaker + custom geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from .mesh_bridge import mesh_info_from_node, require_vred_mesh_api


@dataclass
class MeshSnapshot:
    name: str
    positions: List[float]
    indices: List[int]
    texcoords: List[float]
    texcoord_dim: int
    feasibility_note: str


SPIKE_CONCLUSION = (
    "VRED mesh UVs are readable via vrdGeometryNode.getTexCoords(), but "
    "ASWF TextureBaker currently bakes flat 0-1 texture space and has "
    "limited geometry-node support. Per-mesh UV-layout baking requires "
    "injecting exported mesh data into a MaterialX document and further "
    "research; batch flat UV 0-1 baking is the supported workflow."
)


def export_mesh_snapshot(node) -> Optional[MeshSnapshot]:
    """Export positions, indices, and UVs from a VRED geometry node."""
    require_vred_mesh_api()
    info = mesh_info_from_node(node)
    if info is None:
        return None

    from vrKernelServices import vrdGeometryNode, vrdNode  # type: ignore

    geo = vrdGeometryNode(vrdNode(node))
    if not geo.isValid():
        return None

    positions: List[float] = []
    indices: List[int] = []
    texcoords: List[float] = []
    dim = 0

    try:
        positions = list(geo.getPositions())
    except (RuntimeError, AttributeError):
        pass
    try:
        indices = list(geo.getIndices())
    except (RuntimeError, AttributeError):
        pass
    try:
        import vrUVTypes  # type: ignore
        material_uv = vrUVTypes.UVSet.MaterialUVSet
        if geo.hasUVSet(material_uv):
            texcoords = list(geo.getTexCoords(material_uv))
            dim = int(geo.getTexCoordsDimension(material_uv))
    except (RuntimeError, AttributeError, ImportError):
        pass

    return MeshSnapshot(
        name=info.name,
        positions=positions,
        indices=indices,
        texcoords=texcoords,
        texcoord_dim=dim,
        feasibility_note=SPIKE_CONCLUSION,
    )


def build_minimal_mtlx_mesh(snapshot: MeshSnapshot) -> str:
    """Return XML snippet describing exported mesh (research artifact only)."""
    if not snapshot.positions or not snapshot.indices:
        return "<!-- mesh export incomplete -->"
    return (
        "<!-- VredX mesh export spike: not wired to TextureBaker yet -->\n"
        "<mesh name=\"%s\">\n"
        "  <!-- %d positions, %d indices, %d uv floats -->\n"
        "</mesh>"
        % (snapshot.name, len(snapshot.positions), len(snapshot.indices),
           len(snapshot.texcoords))
    )
