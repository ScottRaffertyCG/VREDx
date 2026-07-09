# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""Output format mapping for MaterialX TextureBaker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BakeFormat = Literal["png", "exr"]

RESOLUTION_PRESETS: dict[str, tuple[int, int]] = {
    "256": (256, 256),
    "512": (512, 512),
    "1024": (1024, 1024),
    "2048": (2048, 2048),
    "4096": (4096, 4096),
}


@dataclass(frozen=True)
class FormatSpec:
    name: BakeFormat
    extension: str
    hdr: bool
    base_type: str  # "UINT8" or "FLOAT" — passed to runner


def format_spec(fmt: BakeFormat) -> FormatSpec:
    if fmt == "exr":
        return FormatSpec(name="exr", extension=".exr", hdr=True,
                          base_type="FLOAT")
    return FormatSpec(name="png", extension=".png", hdr=False,
                      base_type="UINT8")


def normalize_resolution(width: int, height: int) -> tuple[int, int]:
    width = max(1, min(8192, int(width)))
    height = max(1, min(8192, int(height)))
    return width, height
