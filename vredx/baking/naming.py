# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""Filename templates for baked texture output."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Mapping

DEFAULT_TEMPLATE = "{material}_{map}"

# Shown on the baking panel filename template field.
FILENAME_TEMPLATE_TOOLTIP = (
    "Filename template tokens:\n"
    "  {material}  — material / graph name\n"
    "  {map}       — baked map (base_color, normal, …)\n"
    "  {mesh}      — mesh name (batch bakes)\n"
    "  {resolution} — bake size in pixels\n"
    "  {timestamp} — bake time (YYYYMMDD_HHMMSS)\n"
    "  {input}     — legacy alias for {map}\n"
    "\n"
    ".png / .exr is appended automatically — do not add {ext} or a trailing dot."
)

_TOKEN_RE = re.compile(r"\{(\w+)\}")
_LEGACY_EXT_RE = re.compile(r"\.?\{ext\}", re.IGNORECASE)


def prepare_user_template(template: str) -> str:
    """Drop legacy ``{ext}`` tokens and trailing dots from a user template."""
    cleaned = _LEGACY_EXT_RE.sub("", (template or "").strip())
    return cleaned.rstrip(".")


def apply_template(
    template: str,
    *,
    material: str,
    input_name: str,
    mesh: str = "",
    resolution: int = 0,
    ext: str = ".png",
    extra: Mapping[str, str] | None = None,
) -> str:
    """Expand ``{material}``, ``{map}``, ``{mesh}``, ``{resolution}``, etc.

    The file extension is appended automatically unless the result already
    ends with a known image extension.
    """
    template = prepare_user_template(template)
    safe_input = _safe_token(input_name)
    tokens = {
        "material": _safe_token(material),
        "map": safe_input,
        "input": safe_input,
        "mesh": _safe_token(mesh) if mesh else "",
        "resolution": str(resolution) if resolution else "",
        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "ext": ext if ext.startswith(".") else "." + ext,
    }
    if extra:
        tokens.update(extra)

    def repl(match):
        key = match.group(1)
        return tokens.get(key, match.group(0))

    name = _TOKEN_RE.sub(repl, template)
    name = name.rstrip(".")
    if not name.lower().endswith(tokens["ext"].lower()):
        name += tokens["ext"]
    return name


def _safe_token(value: str) -> str:
    cleaned = re.sub(r"[^\w\-.]+", "_", (value or "").strip())
    return cleaned or "unnamed"
