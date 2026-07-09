# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""Orchestrate MaterialX texture baking via bundled ASWF subprocess."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

from ..core import mtlx_writer
from ..core.graph import Graph
from .formats import BakeFormat, FormatSpec, format_spec, normalize_resolution
from .maps import (
    BakeMap, discover_bake_maps, filter_baked_images, filter_maps,
    has_geometry_dependent_nodes, input_name_from_bake_filename,
)
from .naming import DEFAULT_TEMPLATE, apply_template, prepare_user_template
from . import runtime


class BakeError(RuntimeError):
    """Raised when baking cannot run or fails."""


@dataclass
class BakeResult:
    output_dir: str
    images: Dict[str, str] = field(default_factory=dict)
    previews: Dict[str, str] = field(default_factory=dict)
    baked_mtlx: str = ""
    warnings: List[str] = field(default_factory=list)
    width: int = 0
    height: int = 0
    format: str = "png"


PulseCallback = Optional[Callable[[str], None]]
LogCallback = Optional[Callable[[str], None]]


def _subprocess_run_kwargs() -> dict:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


class BakeEngine:
    """Write graph to disk and invoke the ASWF TextureBaker subprocess."""

    def __init__(self, pulse: PulseCallback = None, log: LogCallback = None):
        self._pulse = pulse
        self._log = log
        self.last_subprocess_log = ""

    def _emit_log(self, text: str):
        if not text or not text.strip():
            return
        self.last_subprocess_log = (
            self.last_subprocess_log + text
            if self.last_subprocess_log else text
        )
        if self._log:
            self._log(text.rstrip("\n") + "\n")

    def bake_graph(
        self,
        graph: Graph,
        output_dir: str,
        *,
        width: int = 1024,
        height: int = 1024,
        fmt: BakeFormat = "png",
        selected_inputs: Optional[Set[str]] = None,
        template: str = DEFAULT_TEMPLATE,
        mesh_name: str = "",
    ) -> BakeResult:
        maps = discover_bake_maps(graph)
        maps = filter_maps(maps, selected_inputs)
        if not maps:
            raise BakeError("No connected shader inputs to bake.")

        warnings: List[str] = []
        if has_geometry_dependent_nodes(graph):
            warnings.append(
                "Graph uses geometry-dependent nodes; baked results may be "
                "incorrect for world-space or mesh-dependent shading.")

        if not runtime.is_runtime_available():
            raise BakeError(
                "MaterialX bake runtime is not installed. Run "
                "scripts/fetch_materialx_baker.ps1 before building VredX.")

        width, height = normalize_resolution(width, height)
        spec = format_spec(fmt)
        os.makedirs(output_dir, exist_ok=True)

        if self._pulse:
            self._pulse("Writing MaterialX document…")
        with tempfile.NamedTemporaryFile(
                suffix=".mtlx", delete=False) as tmp_mtlx:
            mtlx_path = tmp_mtlx.name
        mtlx_writer.save_document(graph, mtlx_path)

        material_name = maps[0].material_name or graph.name
        aswf_template = _aswf_filename_template(template, spec.extension)

        if self._pulse:
            self._pulse("Baking textures (GPU)…")

        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False) as tmp:
            result_json = tmp.name

        try:
            bake_args = [
                "--input", mtlx_path,
                "--output-dir", output_dir,
                "--output-mtlx-name", "baked.mtlx",
                "--width", str(width),
                "--height", str(height),
                "--format", spec.name,
                "--result-json", result_json,
            ]
            if aswf_template:
                bake_args.extend(["--template", aswf_template])
            for lib in runtime.library_search_paths():
                bake_args.extend(["--library", lib])
            if selected_inputs:
                for name in sorted(selected_inputs):
                    bake_args.extend(["--maps", name])

            cmd = runtime.baker_subprocess_argv(bake_args)
            self._emit_log("$ %s\n" % " ".join(
                '"%s"' % a if " " in a else a for a in cmd))

            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=runtime.subprocess_env(),
                check=False,
                **_subprocess_run_kwargs(),
            )
            if completed.stdout:
                self._emit_log(completed.stdout)
            if completed.stderr:
                self._emit_log(completed.stderr)

            payload = _read_result_json(result_json, completed)
            if not payload.get("ok"):
                detail = (payload.get("error") or completed.stderr
                          or completed.stdout)
                raise BakeError("Texture bake failed:\n%s"
                                % (detail or "unknown error"))

            warnings.extend(payload.get("warnings") or [])
            images = dict(payload.get("images") or {})
            previews = dict(payload.get("previews") or {})
            baked_maps = filter_maps(maps, selected_inputs)
            allowed = {m.input_name for m in baked_maps}
            images, previews = filter_baked_images(
                images, previews, baked_maps, allowed_names=allowed)

            renamed_images, renamed_previews = _rename_outputs(
                images, previews, baked_maps, template, material_name, mesh_name,
                width, spec)

            baked_path = os.path.join(output_dir, "baked.mtlx")
            return BakeResult(
                output_dir=output_dir,
                images=renamed_images,
                previews=renamed_previews,
                baked_mtlx=baked_path if os.path.isfile(baked_path) else "",
                warnings=warnings,
                width=width,
                height=height,
                format=spec.name,
            )
        finally:
            for path in (mtlx_path, result_json):
                try:
                    if path and os.path.isfile(path):
                        os.remove(path)
                except OSError:
                    pass

    def bake_mtlx_file(
        self,
        mtlx_path: str,
        output_dir: str,
        library=None,
        **kwargs,
    ) -> BakeResult:
        from ..core import mtlx_reader
        from ..core.nodedef_library import NodeDefLibrary, snapshot_root
        if library is None:
            root = snapshot_root()
            library = NodeDefLibrary.load(root)
        graph = mtlx_reader.load_document(mtlx_path, library).graph
        graph.source_mtlx_path = mtlx_path
        return self.bake_graph(graph, output_dir, **kwargs)


def _aswf_filename_template(template: str, extension: str) -> str:
    """Map VredX tokens to ASWF baker template variables (no extension)."""
    template = prepare_user_template(template)
    mapping = {
        "{material}": "$MATERIAL",
        "{map}": "$INPUT",
        "{input}": "$INPUT",
        "{mesh}": "$MATERIAL",
        "{resolution}": "",
        "{timestamp}": "",
    }
    result = template
    for old, new in mapping.items():
        result = result.replace(old, new)
    for suffix in (extension, ".png", ".exr", ".PNG", ".EXR"):
        if suffix and result.lower().endswith(suffix.lower()):
            result = result[:-len(suffix)]
            break
    result = result.rstrip(".")
    if "$INPUT" not in result:
        result = "$MATERIAL_$INPUT"
    return result


def _rename_outputs(
    images: Dict[str, str],
    previews: Dict[str, str],
    maps: List[BakeMap],
    template: str,
    material_name: str,
    mesh_name: str,
    resolution: int,
    spec: FormatSpec,
) -> tuple:
    """Optionally rename baker output files to the user template."""
    images, previews = filter_baked_images(images, previews, maps)
    if template == DEFAULT_TEMPLATE and not mesh_name:
        return images, previews

    output_dir = os.path.dirname(next(iter(images.values()), "")) or "."
    new_images: Dict[str, str] = {}
    new_previews: Dict[str, str] = {}
    for bake_map in maps:
        src = images.get(bake_map.input_name)
        if not src or not os.path.isfile(src):
            continue
        dest_name = apply_template(
            template,
            material=material_name,
            input_name=bake_map.input_name,
            mesh=mesh_name,
            resolution=resolution,
            ext=spec.extension,
        )
        dest = os.path.join(output_dir, dest_name)
        if os.path.abspath(src) != os.path.abspath(dest):
            os.replace(src, dest)
        new_images[bake_map.input_name] = dest

        preview_src = previews.get(bake_map.input_name)
        if preview_src and os.path.isfile(preview_src):
            preview_dest = os.path.splitext(dest)[0] + "_preview.png"
            if os.path.abspath(preview_src) != os.path.abspath(preview_dest):
                os.replace(preview_src, preview_dest)
            new_previews[bake_map.input_name] = preview_dest
        elif spec.name == "png":
            new_previews[bake_map.input_name] = dest
    return new_images or images, new_previews or previews


def _read_result_json(path: str, completed: subprocess.CompletedProcess) -> dict:
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            pass
    if completed.stdout.strip():
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError:
            pass
    return {"ok": False, "error": completed.stderr or completed.stdout}
