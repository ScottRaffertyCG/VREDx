# VREDx - MaterialX Authoring for VRED

A VRED script plugin that adds a node-graph editor for **authoring, editing, and
applying MaterialX materials** inside Autodesk VRED Pro.

![VredX node editor in VRED](media/vredx_node_editor.png)

## Features

- **Palette from your VRED session** — nodedef libraries load from
  `VRED_ROOT` (set by VRED at runtime), so the plugin works from Program
  Files Scripts or Documents `ScriptPlugins`
- **Node canvas** — typed ports, bezier wires, magnetic pin snapping, undo/redo
- **VRED bridge** — Send to VRED, Send & Apply, optional Auto Update, preview swatch
- **Validation** — type/cycle checks and VRED-specific warnings before send
- **Texture baking** — flat UV 0-1 bake to PNG/EXR via bundled ASWF MaterialX
  (Window → Baking panel; VREDX → Bake Textures…)

## Requirements

- Autodesk VRED Pro with MaterialX support (2024+; tested on 2027 / VREDPro-19.1)
- Runtime: VRED's bundled Python + PySide6 (no extra packages)

## Install

### GitHub Release (recommended)

1. Download **VredX-x.y.z.zip** from [Releases](https://github.com/ScottRaffertyCG/VREDx/releases).
2. Extract into **either** install location below (match the version folder to
   your VRED install, e.g. `VRED-19.1` / `VREDPro-19.1` for VRED 2027).
3. Confirm the result is a `VredX\` folder containing `VredX.py` and
   `vredx.zip` (no loose `vredx/` folder).
4. Restart VRED, then open **VREDX** from the menu bar or Scripts panel.

**Program Files** (machine-wide; elevated prompt if VRED is under Program Files):

```
C:\Program Files\Autodesk\VREDPro-19.1\lib\plugins\WIN64\Scripts
```

**Documents ScriptPlugins** (per-user; no admin required):

```
C:\Users\<you>\Documents\Autodesk\VRED-19.1\ScriptPlugins
```

Both locations work. VredX loads its node palette from `VRED_ROOT` (set by
VRED at runtime), not from the plugin folder path.

### From source

Before building a release that includes texture baking, fetch the ASWF
MaterialX runtime (Apache 2.0; bundled inside `vredx.zip`):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/fetch_materialx_baker.ps1
python build.py
```

Copy this repository into either location above as `VredX\`, then zip the
`vredx/` folder to `vredx.zip` and delete the loose `vredx/` folder before
starting VRED.

**Do not leave loose `.py` files under `vredx/`.** VRED's plugin scanner executes
every loose `.py` file it finds. The zip keeps the library importable via
`sys.path` without being scanned.

### What gets installed

```
VredX/
  VredX.py          ← only loose Python entry point VRED executes at startup
  vredx.zip         ← entire editor library (imported, not scanned)
  baking_runtime/   ← shipped in release; move to Documents (see below)
  presets/          ← starter materials
  examples/         ← sample graphs
  resources/        ← icons
  README.md
  LICENSE
```

**Texture baking runtime** (shipped in release zips, **not** left in ScriptPlugins):

```
VredX/
  VredX.py
  vredx.zip
  baking_runtime/
    materialx/          ← ASWF MaterialX 1.39.5 + embeddable Python 3.13
```

Move `baking_runtime` to the installed location (outside ScriptPlugins):

```
Documents/Autodesk/VredX/baking_runtime/
```

Until that move is done, VredX starts normally but **hides** the Baking tab and
menu entries. The ASWF bundle must not stay under ScriptPlugins — VRED scans
loose `.py` files there.

Maintainers: run `scripts/fetch_materialx_baker.ps1` before `python build.py`
so `baking_runtime/` is populated in the release folder.

## Presets

Starter graphs in `presets/` — open from the editor **File → Open…** menu:

| File | Description |
|------|-------------|
| `carpaint.mtlx` | Metallic carpaint with clearcoat |
| `geomprop_demo.mtlx` | Vertex color and scene-data lookups |
| `gltf_pbr.mtlx` | glTF metallic-roughness gold |
| `open_pbr_surface.mtlx` | OpenPBR surface basics |
| `standard_surface_pbr.mtlx` | Standard surface PBR (diffuse + specular) |
| `textured_pbr.mtlx` | Image-map slots for full PBR (base, roughness, metalness, normal) |

## Examples

Sample materials in `examples/` — open from **Examples** in the editor menu:

| File | Category | Description |
|------|----------|-------------|
| `bxdf_carpaint_clearcoat.mtlx` | BxDF | Metallic carpaint + clearcoat |
| `bxdf_disney_principled.mtlx` | BxDF | Disney Principled diffuse |
| `bxdf_gltf_metallic.mtlx` | BxDF | glTF metallic-roughness gold |
| `bxdf_lama_mix_metals.mtlx` | BxDF | LamaMix diffuse + conductor stack |
| `bxdf_open_pbr_basic.mtlx` | BxDF | OpenPBR surface basics |
| `bxdf_standard_surface_emission.mtlx` | BxDF | Emissive standard_surface |
| `bxdf_standard_surface_glass.mtlx` | BxDF | Transmission glass with IOR |
| `bxdf_standard_surface_metal_aniso.mtlx` | BxDF | Anisotropic brushed metal |
| `bxdf_standard_surface_opacity.mtlx` | BxDF | Semi-transparent opacity |
| `bxdf_standard_surface_plastic.mtlx` | BxDF | Matte plastic standard_surface |
| `bxdf_standard_surface_thin_film.mtlx` | BxDF | Thin-film interference |
| `bxdf_surface_unlit.mtlx` | BxDF | Unlit emissive surface |
| `bxdf_usd_preview_surface.mtlx` | BxDF | USD Preview Surface with clearcoat |
| `geomprop_vertex_ao.mtlx` | Scene data | Vertex AO via geompropvalue |
| `geomprop_vertex_color.mtlx` | Scene data | Vertex color lookup |
| `geomprop_world_position.mtlx` | Scene data | World position as base color |
| `limitation_displacement_height.mtlx` | Limitation | Displacement hookup (broken in VRED) |
| `math_mix_float.mtlx` | Math | mix between two constant colors |
| `math_separate_combine.mtlx` | Math | separate3 / combine3 channel shuffle |
| `math_switch_colors.mtlx` | Math | switch node between color inputs |
| `npr_gooch_shading.mtlx` | NPR | Gooch shading into base_color |
| `procedural_cell_noise.mtlx` | Procedural | cellnoise2d mixed between two colors |
| `procedural_checkerboard.mtlx` | Procedural | Checkerboard base color |
| `procedural_fractal_marble.mtlx` | Procedural | fractal3d marble-like pattern |
| `procedural_noise_ramp.mtlx` | Procedural | noise2d color pattern on default UVs |
| `texture_image_pbr_maps.mtlx` | Texture | Image map slots for full PBR |
| `texture_normal_from_height.mtlx` | Texture | Height map to normal via heighttonormal |
| `texture_tiled_checker.mtlx` | Texture | Tiled image with UV scale |
| `texture_triplanar_defaults.mtlx` | Texture | Triplanar projection default colors |
| `texture_uv_transform_noise.mtlx` | Texture | UV scale + rotate2d + noise2d |

## How it runs in VRED

1. VRED scans `…/Scripts/` and executes **one** loose file: `VredX/VredX.py`.
2. That entry point adds `vredx.zip` to `sys.path` and imports the `vredx` package.
3. `VredXPlugin` creates the dockable UI and registers the **VREDX** menu.
4. MaterialX nodedefs are loaded from
   `<VRED_ROOT>/runtimeData/MaterialX/libraries` (provided by the running
   VRED session).

Without the zip packaging, dozens of loose `.py` files under `vredx/` would each
be executed by VRED at startup — slow, noisy, and broken for relative imports.

## Repository contents

This repo ships **plugin source + README**. It does **not** include:

| Excluded | Reason |
|----------|--------|
| `docs/` | Developer reference (e.g. support matrix); not installed with the plugin |
| `tests/` | Dev/CI only (keep locally or in a separate CI repo) |
| `.pytest_cache/` | Local test cache |
| `resources/libraries/` | Large MaterialX snapshot; runtime uses VRED's live libraries |

## License

MIT — see [LICENSE](LICENSE).
