# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""VRED geometry and UV queries for batch baking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..vredbridge import vred_api

INSIDE_VRED = vred_api.INSIDE_VRED

_UV_STATUS_OK = "ok"
_UV_STATUS_MISSING = "missing"
_UV_STATUS_UNKNOWN = "unknown"


@dataclass(frozen=True)
class MeshInfo:
    name: str
    unique_path: str
    uv_status: str
    uv_set_count: int = 0
    material_name: str = ""


def require_vred_mesh_api():
    if not INSIDE_VRED:
        raise RuntimeError("Mesh baking requires VRED.")


def selected_geometry_meshes() -> List[MeshInfo]:
    """Return geometry nodes from the current VRED selection."""
    require_vred_mesh_api()
    service = vred_api.vrScenegraphService
    if service is None:
        return []

    from vrKernelServices import vrdGeometryNode, vrdNode  # type: ignore

    try:
        import vrUVTypes  # type: ignore
        material_uv = vrUVTypes.UVSet.MaterialUVSet
    except ImportError:
        material_uv = 0

    results: List[MeshInfo] = []
    for node in service.getSelectedNodes():
        geo = _as_geometry(node, vrdGeometryNode, vrdNode)
        if geo is None:
            continue
        results.append(_mesh_info(geo, material_uv))
    return results


def mesh_info_from_node(node) -> Optional[MeshInfo]:
    require_vred_mesh_api()
    from vrKernelServices import vrdGeometryNode, vrdNode  # type: ignore
    try:
        import vrUVTypes  # type: ignore
        material_uv = vrUVTypes.UVSet.MaterialUVSet
    except ImportError:
        material_uv = 0
    geo = _as_geometry(node, vrdGeometryNode, vrdNode)
    if geo is None:
        return None
    return _mesh_info(geo, material_uv)


def _as_geometry(node, vrdGeometryNode, vrdNode):
    try:
        geo = vrdGeometryNode(vrdNode(node))
        if geo.isValid():
            return geo
    except (RuntimeError, TypeError, AttributeError):
        pass
    try:
        if hasattr(node, "isType") and node.isType(vrdGeometryNode):
            geo = vrdGeometryNode(node)
            if geo.isValid():
                return geo
    except (RuntimeError, TypeError, AttributeError):
        pass
    return None


def _mesh_info(geo, material_uv) -> MeshInfo:
    name = ""
    path = ""
    try:
        name = geo.getName()
        path = geo.getUniquePath()
    except (RuntimeError, AttributeError):
        pass

    uv_status = _UV_STATUS_UNKNOWN
    uv_count = 0
    try:
        if geo.hasUVSet(material_uv):
            coords = geo.getTexCoords(material_uv)
            dim = geo.getTexCoordsDimension(material_uv)
            if coords and dim > 0:
                uv_status = _UV_STATUS_OK
                uv_count = 1
            else:
                uv_status = _UV_STATUS_MISSING
        else:
            uv_status = _UV_STATUS_MISSING
    except (RuntimeError, AttributeError):
        uv_status = _UV_STATUS_UNKNOWN

    material_name = ""
    try:
        mat = geo.getMaterial()
        if mat is not None and mat.isValid():
            material_name = mat.getName()
    except (RuntimeError, AttributeError):
        pass

    return MeshInfo(
        name=name or "geometry",
        unique_path=path,
        uv_status=uv_status,
        uv_set_count=uv_count,
        material_name=material_name,
    )


def uv_status_label(status: str) -> str:
    return {
        _UV_STATUS_OK: "Has UV",
        _UV_STATUS_MISSING: "Missing UV",
        _UV_STATUS_UNKNOWN: "Unknown",
    }.get(status, status)
