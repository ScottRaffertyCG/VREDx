# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""CLI for headless MaterialX texture baking."""

from __future__ import annotations

import argparse
import sys

from .engine import BakeEngine, BakeError
from .naming import DEFAULT_TEMPLATE
from .runtime import default_bakes_dir


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Bake MaterialX shader inputs to textures (VredX)")
    parser.add_argument("input", help="Source .mtlx file")
    parser.add_argument("-o", "--output-dir", default="")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--format", choices=("png", "exr"), default="png")
    parser.add_argument("--maps", nargs="*", default=None,
                        help="Shader input names to bake (default: all)")
    parser.add_argument("--template", default=DEFAULT_TEMPLATE)
    args = parser.parse_args(argv)

    output_dir = args.output_dir or default_bakes_dir("cli_bake")
    selected = set(args.maps) if args.maps else None
    engine = BakeEngine()
    try:
        result = engine.bake_mtlx_file(
            args.input,
            output_dir,
            width=args.width,
            height=args.height,
            fmt=args.format,
            selected_inputs=selected,
            template=args.template,
        )
    except BakeError as exc:
        print("Error:", exc, file=sys.stderr)
        return 1

    print("Baked %d map(s) to %s" % (len(result.images), result.output_dir))
    for name, path in sorted(result.images.items()):
        print("  %s: %s" % (name, path))
    if result.warnings:
        print("Warnings:")
        for warning in result.warnings:
            print(" ", warning)
    return 0


if __name__ == "__main__":
    sys.exit(main())
