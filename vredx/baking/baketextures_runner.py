#!/usr/bin/env python
# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.
#
# Subprocess entry point for ASWF MaterialX TextureBaker.
# Run with the bundled MaterialX Python from third_party/materialx/.
# Do not modify the ASWF runtime; this script is VredX-owned glue code.

"""Bake a .mtlx document to textures (flat UV 0-1) and emit JSON metadata."""

from __future__ import annotations

import argparse
import json
import os
import sys
from sys import platform

from vredx.baking.maps import input_name_from_bake_filename


def _import_materialx():
    import MaterialX as mx  # noqa: WPS433 — optional subprocess dependency
    from MaterialX import PyMaterialXRender as mx_render
    if platform == "darwin":
        from MaterialX import PyMaterialXRenderMsl as mx_render_backend
    else:
        from MaterialX import PyMaterialXRenderGlsl as mx_render_backend
    return mx, mx_render, mx_render_backend


def _write_exr_preview(exr_path: str, preview_path: str) -> bool:
    """Tonemap an EXR to 8-bit PNG for Qt preview."""
    try:
        import MaterialX as mx
        from MaterialX import PyMaterialXRender as mx_render
        image = mx_render.Image.create(1, 1, mx_render.BaseType.UINT8)
        loaded = mx_render.Image.load(exr_path)
        if loaded is None:
            return False
        width, height = loaded.getWidth(), loaded.getHeight()
        preview = mx_render.Image.create(width, height, mx_render.BaseType.UINT8)
        for y in range(height):
            for x in range(width):
                rgba = loaded.getRGBA(x, y)
                preview.setRGBA(x, y, (
                    min(1.0, max(0.0, rgba[0])),
                    min(1.0, max(0.0, rgba[1])),
                    min(1.0, max(0.0, rgba[2])),
                    min(1.0, max(0.0, rgba[3] if len(rgba) > 3 else 1.0)),
                ))
        preview.save(preview_path)
        return os.path.isfile(preview_path)
    except Exception:
        pass
    try:
        import OpenEXR
        import Imath
        import numpy as np
        from PIL import Image
    except ImportError:
        return False
    try:
        exr = OpenEXR.InputFile(exr_path)
        header = exr.header()
        dw = header["dataWindow"]
        width = dw.max.x - dw.min.x + 1
        height = dw.max.y - dw.min.y + 1
        pt = Imath.PixelType(Imath.PixelType.FLOAT)
        channels = header["channels"].keys()
        rgb = []
        for ch in ("R", "G", "B"):
            if ch in channels:
                raw = exr.channel(ch, pt)
                rgb.append(np.frombuffer(raw, dtype=np.float32).reshape(height, width))
        if len(rgb) < 3:
            return False
        data = np.stack(rgb, axis=-1)
        data = np.clip(data, 0.0, None)
        scale = data.max()
        if scale > 0:
            data = data / scale
        img = (data * 255.0).astype("uint8")
        Image.fromarray(img, mode="RGB").save(preview_path)
        return True
    except Exception:
        return False


def bake(args) -> dict:
    mx, mx_render, mx_render_backend = _import_materialx()

    stdlib = mx.createDocument()
    search_path = mx.getDefaultDataSearchPath()
    search_path.append(os.path.dirname(os.path.abspath(args.input)))
    for lib_dir in args.library or []:
        if lib_dir and os.path.isdir(lib_dir):
            search_path.append(lib_dir)

    library_folders = list(mx.getDefaultDataLibraryFolders())
    mx.loadLibraries(library_folders, search_path, stdlib)

    doc = mx.createDocument()
    mx.readFromXmlFile(doc, args.input)
    doc.setDataLibrary(stdlib)

    valid, msg = doc.validate()
    warnings = []
    if not valid:
        warnings.append(msg)

    if not doc.getMaterialNodes():
        raise RuntimeError("No surfacematerial elements found in input document.")

    os.makedirs(args.output_dir, exist_ok=True)
    output_mtlx = os.path.join(args.output_dir, args.output_mtlx_name)

    base_type = (mx_render.BaseType.FLOAT if args.hdr
                 else mx_render.BaseType.UINT8)
    baker = mx_render_backend.TextureBaker.create(
        args.width, args.height, base_type)
    baker.setExtension(args.extension)
    baker.writeDocumentPerMaterial(True)
    if args.template:
        baker.setTextureFilenameTemplate(args.template)
    baker.bakeAllMaterials(doc, search_path, output_mtlx)

    images = {}
    previews = {}
    selected = set(args.maps) if args.maps else None

    for name in os.listdir(args.output_dir):
        lower = name.lower()
        if not (lower.endswith(args.extension.lower())
                or lower.endswith(".png") or lower.endswith(".exr")):
            continue
        if name.endswith("_preview.png"):
            continue
        full = os.path.join(args.output_dir, name)
        if not os.path.isfile(full):
            continue
        input_key = input_name_from_bake_filename(name, selected)
        if input_key is None:
            continue
        images[input_key] = full
        if lower.endswith(".exr"):
            preview = os.path.splitext(full)[0] + "_preview.png"
            if _write_exr_preview(full, preview):
                previews[input_key] = preview
        elif lower.endswith(".png"):
            previews[input_key] = full

    if selected:
        images = {k: v for k, v in images.items() if k in selected}
        previews = {k: v for k, v in previews.items() if k in selected}

    return {
        "ok": True,
        "output_dir": args.output_dir,
        "baked_mtlx": output_mtlx if os.path.isfile(output_mtlx) else "",
        "images": images,
        "previews": previews,
        "warnings": warnings,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="VredX MaterialX texture baker")
    parser.add_argument("--input", required=True, help="Source .mtlx path")
    parser.add_argument("--output-dir", required=True, help="Output folder")
    parser.add_argument("--output-mtlx-name", default="baked.mtlx")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--format", choices=("png", "exr"), default="png")
    parser.add_argument("--template", default="")
    parser.add_argument("--library", action="append", default=[])
    parser.add_argument("--maps", action="append", default=[])
    parser.add_argument("--result-json", default="",
                        help="Write bake metadata JSON to this path")
    opts = parser.parse_args(argv)

    opts.hdr = opts.format == "exr"
    opts.extension = ".exr" if opts.hdr else ".png"

    try:
        payload = bake(opts)
    except Exception as exc:
        payload = {"ok": False, "error": str(exc), "images": {}, "previews": {}}

    text = json.dumps(payload, indent=2)
    if opts.result_json:
        with open(opts.result_json, "w", encoding="utf-8") as handle:
            handle.write(text)
    else:
        print(text)
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
