# ASWF MaterialX Runtime (bundled)

This folder holds the official ASWF MaterialX prebuilt release used by VredX
texture baking. It is **not modified** by VredX (Apache License 2.0).

## Maintainer setup

From the VredX repository root, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/fetch_materialx_baker.ps1
python build.py
```

The fetch script downloads MaterialX 1.39.5 for Windows (Python 3.13) plus an
embeddable CPython 3.13 interpreter. Release builds copy the runtime to
`baking_runtime/materialx/` next to `VredX.py` (it is stripped from `vredx.zip`).

## Release layout

```
VredX/
  VredX.py
  vredx.zip
  baking_runtime/
    materialx/          ← ASWF bundle (move — see below)
```

## End-user install

Move the shipped `baking_runtime` folder to:

```
Documents/Autodesk/VredX/baking_runtime/
```

VRED must not load the ASWF Python tree from ScriptPlugins (it scans loose
`.py` files). Until the runtime is moved, VredX works normally but hides all
baking UI.

## Expected layout after fetch

```
materialx/
  bin/              native DLLs and MaterialXView
  python/           PyMaterialX cp313 extension modules
  python313/        embeddable CPython 3.13 (runs the baker subprocess)
  libraries/        MaterialX nodedef libraries
```

## License

See ../NOTICE.txt and ../LICENSE-ASWF-MaterialX.txt
