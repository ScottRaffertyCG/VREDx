# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""Sequential batch texture baking."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Set

from ..core.graph import Graph
from .engine import BakeEngine, BakeError, BakeResult
from .formats import BakeFormat
from .naming import DEFAULT_TEMPLATE


@dataclass
class BatchEntry:
    """One item in a batch bake queue."""
    mesh_name: str
    material_name: str
    graph: Graph
    output_subdir: str = ""
    template_override: str = ""
    uv_status: str = "unknown"


@dataclass
class BatchResult:
    entries: List[BatchEntry] = field(default_factory=list)
    results: List[BakeResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


ProgressCallback = Optional[Callable[[int, int, str], None]]


class BatchBaker:
    """Bake multiple graphs sequentially to a shared output folder."""

    def __init__(self, pulse: ProgressCallback = None, log=None):
        self._pulse = pulse
        self._log = log
        self._engine = BakeEngine(log=log)

    def run(
        self,
        entries: List[BatchEntry],
        output_root: str,
        *,
        width: int = 1024,
        height: int = 1024,
        fmt: BakeFormat = "png",
        selected_inputs: Optional[Set[str]] = None,
        template: str = DEFAULT_TEMPLATE,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> BatchResult:
        batch = BatchResult(entries=list(entries))
        total = len(entries)
        for index, entry in enumerate(entries, start=1):
            if cancel_check and cancel_check():
                batch.errors.append("Batch cancelled by user.")
                break
            label = entry.mesh_name or entry.material_name
            if self._pulse:
                self._pulse(index, total, label)
            subdir = entry.output_subdir or "%s_%s" % (
                _safe_name(entry.mesh_name or "mesh"),
                _safe_name(entry.material_name or "material"),
            )
            out_dir = os.path.join(output_root, subdir)
            row_template = entry.template_override or template
            try:
                result = self._engine.bake_graph(
                    entry.graph,
                    out_dir,
                    width=width,
                    height=height,
                    fmt=fmt,
                    selected_inputs=selected_inputs,
                    template=row_template,
                    mesh_name=entry.mesh_name,
                )
            except BakeError as exc:
                batch.errors.append("%s: %s" % (label, exc))
                continue
            batch.results.append(result)
        return batch


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^\w\-.]+", "_", (value or "").strip())
    return cleaned or "unnamed"
